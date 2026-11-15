import asyncio
import json
from collections.abc import AsyncIterator, Callable

import pytest

from tests.conftest import FakeBackend, RecordingSurface, finish_tasks, output, settle
from tests.fake_mqtt import FakeBroker
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon import protocol
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import BehaviorConfig, MqttConfig, parse_config
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.protocol import Button, Color, Led, RingMode
from xtouch_daemon.strips import build_strip
from xtouch_daemon.strips import homeassistant as homeassistant_module
from xtouch_daemon.strips.base import StripEnv, VolumeStrip
from xtouch_daemon.strips.homeassistant import EVENT_TYPES, HomeAssistantStrip, LatestValue

TOPIC = "homeassistant/{component}/xtouch/lights_{part}/{kind}"


def topic(component: str, part: str, kind: str = "state") -> str:
    return TOPIC.format(component=component, part=part, kind=kind)


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(300):
        if condition():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("the condition never became true")


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def bridge(broker: FakeBroker, monkeypatch: pytest.MonkeyPatch) -> MqttBridge:
    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    monkeypatch.setattr(homeassistant_module, "FADER_PUBLISH_INTERVAL", 0.005)
    return MqttBridge(MqttConfig(host="broker"), client_factory=broker.client)


@pytest.fixture
async def strip(surface: RecordingSurface, bridge: MqttBridge) -> AsyncIterator[HomeAssistantStrip]:
    env = StripEnv(FakeBackend(), BehaviorConfig(encoder_step=5), bridge)
    controller = HomeAssistantStrip(surface.strips[0], env, bridge, "lights", "Lights", "cyan")
    yield controller
    controller.close()
    await finish_tasks()


async def connect(strip: HomeAssistantStrip, bridge: MqttBridge) -> None:
    bridge.on_connection = lambda connected: strip.show()
    await bridge.set_entities(strip.entities)
    bridge_task = asyncio.create_task(bridge.run())
    await until(lambda: bridge.ready and strip.fader.state is not None)
    assert not bridge_task.done()


def move(strip: HomeAssistantStrip, surface: RecordingSurface, fraction: float) -> None:
    """A hand moves the fader (the surface knows where it is then, the strip gets the event)."""
    surface.strips[0].moved_by_hand(protocol.fader_value(fraction))
    strip.on_fader(fraction)


def published(broker: FakeBroker, state_topic: str) -> list[str]:
    return [payload for t, payload, _ in broker.published if t == state_topic]


async def test_without_home_assistant_the_strip_shows_its_configuration_and_offline(
    strip: HomeAssistantStrip, surface: RecordingSurface
) -> None:
    strip.update(AudioState())

    s = surface.strips[0]
    assert s.text == ["Lights", "offline"]
    assert s.color == Color.CYAN
    assert all(s.leds[button] == Led.OFF for button in Button)


async def test_the_entities_start_with_the_configuration(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)

    assert broker.retained[topic("text", "top")] == "Lights"
    assert broker.retained[topic("select", "color")] == "cyan"
    assert broker.retained[topic("select", "mute_led")] == "off"
    assert surface.strips[0].text == ["Lights", ""]
    assert surface.strips[0].color == Color.CYAN
    discovery = json.loads(broker.retained[topic("text", "top", "config")])
    assert discovery["max"] == protocol.LCD_CELL_WIDTH
    assert discovery["name"] == "Lights top line"
    events = json.loads(broker.retained[topic("event", "buttons", "config")])
    assert events["event_types"] == EVENT_TYPES
    assert events["device_class"] == "button"


async def test_home_assistant_drives_the_strip(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)

    broker.publish(topic("number", "fader", "set"), "75")
    broker.publish(topic("number", "encoder", "set"), "100")
    broker.publish(topic("text", "top", "set"), "Desk")
    broker.publish(topic("text", "bottom", "set"), "80%")
    broker.publish(topic("select", "color", "set"), "red")
    broker.publish(topic("select", "mute_led", "set"), "on")
    broker.publish(topic("select", "rec_led", "set"), "flash")
    await until(lambda: surface.strips[0].leds.get(Button.REC) == Led.FLASH)
    await surface.settled()

    s = surface.strips[0]
    assert surface.faders(0)[-1] == protocol.fader_value(0.75)
    assert s.ring == (protocol.RING_MAX, RingMode.WRAP)
    assert s.text == ["Desk", "80%"]
    assert s.color == Color.RED
    assert s.leds[Button.MUTE] == Led.ON
    assert s.leds[Button.SELECT] == Led.OFF


async def test_home_assistant_sets_a_meter_that_holds(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker
) -> None:
    # without a connection the meter shows nothing
    assert strip.held_meter() is None
    await connect(strip, bridge)
    assert broker.retained[topic("number", "meter")] == "0"
    discovery = json.loads(broker.retained[topic("number", "meter", "config")])
    assert (discovery["min"], discovery["max"], discovery["step"]) == (0, 100, 1)
    assert strip.held_meter() == 0

    # 0..100 % over the levels of the meter
    for percent, level in (("50", 7), ("100", protocol.METER_MAX), ("3", 0), ("4", 1), ("150", protocol.METER_MAX)):
        broker.publish(topic("number", "meter", "set"), percent)
        await until(lambda percent=percent: strip.meter_level.target_state == percent)
        assert strip.held_meter() == level, percent


async def test_a_color_that_is_no_color_shows_the_configured_one(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    broker.retained[topic("select", "color")] = "pink"

    await connect(strip, bridge)

    assert surface.strips[0].color == Color.CYAN


async def test_the_fader_publishes_while_it_moves_and_stays_where_it_was_let_go(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)
    await surface.settled()
    surface.sent.clear()

    strip.on_touch(True)
    surface.strips[0].touch(True)
    move(strip, surface, 0.1)
    await until(lambda: strip.fader.state == "10")
    # moves while it waits to publish again: only the newest one goes out
    for fraction in (0.2, 0.3, 0.4, 0.5):
        move(strip, surface, fraction)
    strip.on_touch(False)
    surface.strips[0].touch(False)
    await until(lambda: strip.fader.state == "50")
    await surface.settled()

    values = published(broker, topic("number", "fader"))
    # not every step: the first, then the newest
    assert values == ["0", "10", "50"]
    # the motor did not move it back to an older value on its way
    assert surface.faders(0) == []
    events = [json.loads(p)["event_type"] for p in published(broker, topic("event", "buttons"))]
    assert events == ["fader_touched", "fader_released"]


async def test_a_release_without_move_keeps_the_fader(
    strip: HomeAssistantStrip, bridge: MqttBridge, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)
    await surface.settled()
    surface.sent.clear()

    strip.on_touch(True)
    strip.on_touch(False)
    await surface.settled()

    assert surface.faders(0) == []


async def test_the_encoder_sets_its_number_in_steps(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)

    strip.on_encoder(3)
    strip.on_encoder(-1)
    assert surface.strips[0].ring == (round(0.1 * (protocol.RING_MAX - 1)) + 1, RingMode.WRAP)
    await until(lambda: strip.encoder.state == "10")
    strip.on_encoder(-10)
    await until(lambda: strip.encoder.state == "0")
    strip.on_encoder(100)
    await until(lambda: strip.encoder.state == "100")

    assert published(broker, topic("number", "encoder"))[-1] == "100"


async def test_buttons_and_the_encoder_send_events(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)

    strip.on_button(Button.MUTE, True)
    strip.on_button(Button.MUTE, False)
    strip.on_encoder_press(True)
    strip.on_encoder_press(False)
    events_topic = topic("event", "buttons")
    await until(lambda: len(published(broker, events_topic)) == 4)

    events = [json.loads(payload)["event_type"] for payload in published(broker, events_topic)]
    assert events == ["mute_pressed", "mute_released", "encoder_pressed", "encoder_released"]
    # a press does not switch the LED: that is up to Home Assistant
    assert surface.strips[0].leds[Button.MUTE] == Led.OFF


async def test_without_home_assistant_the_device_does_nothing(strip: HomeAssistantStrip, broker: FakeBroker) -> None:
    strip.on_fader(0.5)
    strip.on_encoder(2)
    strip.on_button(Button.SOLO, True)
    strip.on_touch(True)
    await asyncio.sleep(0.01)

    assert broker.published == []


async def test_a_strip_shows_offline_when_the_broker_is_gone(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)
    broker.publish(topic("text", "bottom", "set"), "on")
    await until(lambda: surface.strips[0].text[1] == "on")

    broker.refuse = 1000
    broker.disconnect()
    await until(lambda: surface.strips[0].text[1] == "offline")


async def test_a_closed_strip_no_longer_follows_home_assistant(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)

    strip.close()
    broker.publish(topic("text", "top", "set"), "Other")
    await until(lambda: strip.top.state == "Other")

    assert surface.strips[0].text[0] == "Lights"


async def test_a_strip_without_label_is_named_by_its_position(surface: RecordingSurface, bridge: MqttBridge) -> None:
    env = StripEnv(FakeBackend(), BehaviorConfig(), bridge)
    strip = HomeAssistantStrip(surface.strips[2], env, bridge, "strip_3")

    assert strip.fader.name == "Strip 3 fader"
    assert strip.fader.entity_id == "number.xtouch_strip_3_fader"
    assert strip.entities[strip.top] == ""
    assert strip.entities[strip.lcd_color] == "white"
    strip.close()


class GatedNumber:
    """A number entity whose publishing waits for `gate`."""

    def __init__(self) -> None:
        self.target_state: str | None = "0"
        self.entity_id = "number.gated"
        self.gate = asyncio.Event()
        self.published: list[float] = []

    async def set_state(self, value: float) -> None:
        await self.gate.wait()
        self.published.append(value)
        self.target_state = str(value)


async def test_a_value_set_while_the_last_one_is_published_goes_out_after_it() -> None:
    entity = GatedNumber()
    latest = LatestValue(entity, 0)  # type: ignore[arg-type]

    latest.set(10)
    await asyncio.sleep(0)
    latest.set(20)
    latest.set(30)
    assert latest.value == 30
    entity.gate.set()
    await until(lambda: latest.wanted is None)

    assert entity.published == [10, 30]
    assert latest.value == 30
    latest.cancel()


async def test_a_new_configuration_waits_for_the_states_of_its_entities(
    strip: HomeAssistantStrip, bridge: MqttBridge, broker: FakeBroker, surface: RecordingSurface
) -> None:
    await connect(strip, bridge)
    env = StripEnv(FakeBackend(), BehaviorConfig(), bridge)
    new = HomeAssistantStrip(surface.strips[1], env, bridge, "other", "Other")

    new.update(AudioState())
    new.on_encoder(1)

    assert surface.strips[1].text == ["Other", "offline"]
    new.close()


# -- the fader or the encoder of an audio strip in Home Assistant ----------------------------------------------------

SPEAKER = AudioState(outputs=(output("speaker", 50),))


def audio_strip(surface: RecordingSurface, bridge: MqttBridge, config: str) -> VolumeStrip:
    env = StripEnv(FakeBackend(), BehaviorConfig(encoder_step=5), bridge)
    (strip_config,) = parse_config(config + MQTT).strips
    controller = build_strip(strip_config, surface.strips[0], env, {})
    assert isinstance(controller, VolumeStrip)
    return controller


async def connect_audio(strip: VolumeStrip, bridge: MqttBridge) -> None:
    bridge.on_connection = lambda connected: strip.show()
    await bridge.set_entities(strip.entities)
    running.append(asyncio.create_task(bridge.run()))
    await until(lambda: strip.controls is not None and strip.controls.connected)


MQTT = '[mqtt]\nhost = "broker"\n'
running: list[asyncio.Task[None]] = []


async def test_the_encoder_of_an_audio_strip_is_a_number_of_home_assistant(
    surface: RecordingSurface, bridge: MqttBridge, broker: FakeBroker
) -> None:
    strip = audio_strip(
        surface, bridge, '[[strip]]\ntype = "output"\ndevice = "speaker"\nid = "lights"\nencoder = "homeassistant"\n'
    )
    strip.update(SPEAKER)
    # not there yet: the encoder does nothing
    strip.on_encoder(1)
    strip.on_encoder_press(True)
    assert surface.strips[0].ring == (0, RingMode.DOT)

    await connect_audio(strip, bridge)
    events = json.loads(broker.retained[topic("event", "buttons", "config")])
    assert events["event_types"] == ["encoder_pressed", "encoder_released"]
    assert set(json.loads(broker.retained[topic("number", "encoder", "config")])) >= {"min", "max"}

    broker.publish(topic("number", "encoder", "set"), "50")
    await until(lambda: surface.strips[0].ring == (6, RingMode.WRAP))
    strip.on_encoder(2)
    await until(lambda: published(broker, topic("number", "encoder"))[-1:] == ["60"])
    assert surface.strips[0].text[1] == "60%"
    strip.on_encoder_press(True)
    await until(lambda: len(published(broker, topic("event", "buttons"))) == 1)
    assert json.loads(published(broker, topic("event", "buttons"))[0])["event_type"] == "encoder_pressed"

    # also while the device is gone; the fader still sets the volume
    strip.update(AudioState())
    assert surface.strips[0].ring == (7, RingMode.WRAP)
    strip.on_encoder(-2)
    await until(lambda: published(broker, topic("number", "encoder"))[-1:] == ["50"])
    assert strip.entities == strip.controls.entities  # type: ignore[union-attr]
    strip.close()
    await finish_tasks()


async def test_with_the_fader_in_home_assistant_the_encoder_sets_the_volume(
    surface: RecordingSurface, bridge: MqttBridge, broker: FakeBroker
) -> None:
    strip = audio_strip(
        surface, bridge, '[[strip]]\ntype = "output"\ndevice = "speaker"\nfader = "homeassistant"\nid = "lights"\n'
    )
    backend = strip.env.backend
    assert isinstance(backend, FakeBackend)
    strip.update(SPEAKER)
    # not there yet: the fader does nothing, and stays where it is
    strip.on_fader(0.3)
    assert surface.faders(0) == []

    await connect_audio(strip, bridge)
    broker.publish(topic("number", "fader", "set"), "80")
    await until(lambda: surface.strips[0].fader == protocol.fader_value(0.8))

    strip.on_touch(True)
    move(strip, surface, 0.25)  # type: ignore[arg-type]
    strip.on_touch(False)
    await until(lambda: published(broker, topic("number", "fader"))[-1:] == ["25"])
    await until(lambda: len(published(broker, topic("event", "buttons"))) == 2)

    # the encoder: the volume, without moving the fader
    strip.on_encoder(2)
    await settle()
    strip.on_encoder_press(True)
    await settle()
    assert [call[3] for call in backend.calls] == [60, 100]
    # an idle strip leaves the fader to Home Assistant
    strip.update(AudioState())
    assert surface.strips[0].fader == protocol.fader_value(0.25)
    strip.close()
    await finish_tasks()
