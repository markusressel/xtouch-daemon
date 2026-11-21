"""
Channels, states and slots in Home Assistant: the mode, the states with their overrides and inputs, what the slots
show and which channels are shown.
"""

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from tests.support.audio import output, stream
from tests.support.mqtt import FakeBroker
from tests.support.tasks import finish_tasks
from tests.support.waiting import until
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.sections import MqttConfig
from xtouch_daemon.daemon.homeassistant import SlotEntities
from xtouch_daemon.daemon.slots import SlotEngine
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.slots.states import Override

CONFIG = """
[voip]
provider = "demo"

[channel.out]
type = "output"
device = "speaker"
label = "Speaker"

[channel.web]
type = "apps"
match = ["firefox"]
label = "Web"

[state.call]
processes = ["mumble"]
delay_off = 0

[state.away]
homeassistant = true
delay_off = 0

[state.gaming]
mode = true
label = "Gaming"
processes = ["mygame"]
delay_off = 0

[slots]
1 = "out"
2 = ["web if call", "-"]
3 = "auto"
"""

STATE = AudioState(outputs=(output("speaker", 50),), streams=(stream(1, "Spotify", "spotify"),))


@pytest.fixture
async def setup(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[FakeBroker, MqttBridge]]:
    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    broker = FakeBroker()
    bridge = MqttBridge(MqttConfig(host="broker"), client_factory=broker.client)
    yield broker, bridge
    await bridge.close()
    await finish_tasks()


def attributes(broker: FakeBroker, topic: str) -> dict[str, object]:
    payload = broker.last(topic.removesuffix("/state") + "/attributes")
    assert payload is not None
    return json.loads(payload)


async def test_the_states_the_mode_and_the_slots(setup: tuple[FakeBroker, MqttBridge]) -> None:
    broker, bridge = setup
    config = parse_config(CONFIG + '[mqtt]\nhost = "broker"\n')
    assert config.slots is not None
    engine = SlotEngine(config)
    requests: list[int] = []
    engine.on_request = lambda: requests.append(1)
    inputs: list[int] = []
    entities = SlotEntities(bridge, engine, config.slots, lambda: inputs.append(1))
    ids = {entity.entity_id for entity in entities.entities}
    assert {
        "select.xtouch_mode",
        "binary_sensor.xtouch_state_call",
        "select.xtouch_state_call",
        "switch.xtouch_state_away_input",
        "binary_sensor.xtouch_state_gaming",
        "binary_sensor.xtouch_out_shown",
        "sensor.xtouch_slot_3",
    } <= ids
    assert "select.xtouch_state_gaming" not in ids
    assert "switch.xtouch_state_call_input" not in ids

    # not connected: nothing to publish
    entities.update(engine.step(STATE, frozenset(), None, frozenset(), 0))
    await bridge.set_entities(entities.entities)
    task = asyncio.create_task(bridge.run())
    await until(lambda: bridge.ready)

    result = engine.step(STATE, frozenset({"mumble"}), None, frozenset(), 1)
    entities.update(result)
    await until(lambda: broker.last(entities.states["call"].state_topic) == "ON")
    assert attributes(broker, entities.states["call"].state_topic)["source"] == "mumble runs"
    assert broker.last(entities.slots[1].state_topic) == "out"
    assert attributes(broker, entities.slots[1].state_topic) == {
        "label": "Speaker",
        "kind": "channel",
        "via": "out",
        "reason": "shows out",
    }
    assert broker.last(entities.slots[3].state_topic) == "app:Spotify"
    assert broker.last(entities.slots[4].state_topic) == "none"
    assert broker.last(entities.shown["web"].state_topic) == "ON"
    assert broker.last(entities.shown["out"].state_topic) == "ON"
    since = attributes(broker, entities.states["call"].state_topic)["since"]
    assert isinstance(since, str)
    # the same again: nothing new
    count = len(broker.published)
    entities.update(result)
    await asyncio.sleep(0.01)
    assert len(broker.published) == count

    # Home Assistant: a mode, an override, the input of a state
    broker.publish(entities.mode.command_topic, "gaming")
    await until(lambda: engine.simulation.engine.mode_pick == "gaming")
    broker.publish(entities.mode.command_topic, "nope")
    broker.publish(entities.mode.command_topic, "auto")
    await until(lambda: engine.simulation.engine.mode_pick is None)
    broker.publish(entities.overrides["call"].command_topic, "off")
    await until(lambda: engine.choices[0] == {"call": Override.OFF})
    broker.publish(entities.overrides["call"].command_topic, "maybe")
    assert len(requests) == 3
    broker.publish(entities.inputs["away"].command_topic, "ON")
    await until(lambda: engine.homeassistant == {"away"})
    broker.publish(entities.inputs["away"].command_topic, "ON")
    broker.publish(entities.inputs["away"].command_topic, "OFF")
    await until(lambda: engine.homeassistant == frozenset())
    assert len(inputs) == 2
    broker.publish(entities.inputs["away"].command_topic, "ON")
    await until(lambda: engine.homeassistant == {"away"})
    entities.update(engine.step(STATE, frozenset({"mumble"}), None, frozenset(), 2))
    await until(lambda: broker.last(entities.states["away"].state_topic) == "ON")
    assert broker.last(entities.overrides["call"].state_topic) == "off"
    # call is off by hand: web is not shown
    assert broker.last(entities.shown["web"].state_topic) == "OFF"

    # the broker went away: everything again
    entities.forget()
    count = len(broker.published)
    assert engine.simulation.result is not None
    entities.update(engine.simulation.result)
    await until(lambda: len(broker.published) > count + 10)

    # what is on its way when the configuration goes
    entities.forget()
    entities.update(engine.simulation.result)
    task.cancel()
    entities.close()


async def test_a_person_without_a_channel_is_published_as_a_person(setup: tuple[FakeBroker, MqttBridge]) -> None:
    _, bridge = setup
    config = parse_config(CONFIG.replace('provider = "demo"', 'provider = "demo"\nparticipants = ["Ann"]'))
    assert config.slots is not None
    assert config.voip is not None
    from xtouch_daemon.daemon.lifecycle import voip_state
    from xtouch_daemon.voip.demo import DemoProvider

    engine = SlotEngine(config)
    entities = SlotEntities(bridge, engine, config.slots, lambda: None)
    result = engine.step(STATE, frozenset(), voip_state(DemoProvider(config.voip.participants)), frozenset(), 0)
    published = {slot: entities._slot(slot, result.slots[slot], result.why[slot]) for slot in result.slots}
    assert published[8][0] == "person:Ann"
    assert json.loads(published[8][1] or "")["kind"] == "person"
    entities.close()
