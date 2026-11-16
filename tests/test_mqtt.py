import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.event import MQTTEvent
from haad_mqtt_autodiscovery.entity.number import MQTTNumber
from haad_mqtt_autodiscovery.entity.switch import MQTTSwitch

from tests.conftest import finish_tasks
from tests.fake_mqtt import FakeBroker
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon.config import ConfigError, MqttConfig
from xtouch_daemon.mqtt import MqttBridge

CONFIG = MqttConfig(host="broker", username="xtouch", password="secret")  # type: ignore[arg-type]
AVAILABILITY = "xtouch-daemon/xtouch/availability"


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(200):
        if condition():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("the condition never became true")


def number(identifier: str = "strip_1_fader") -> MQTTNumber:
    return MQTTNumber("xtouch", identifier, identifier, min_val=0, max_val=100)


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def bridge(broker: FakeBroker, monkeypatch: pytest.MonkeyPatch) -> MqttBridge:
    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    return MqttBridge(CONFIG, client_factory=broker.client)


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


async def start(bridge: MqttBridge) -> asyncio.Task[None]:
    task = asyncio.create_task(bridge.run())
    await until(lambda: bridge.ready)
    return task


async def test_entities_are_announced_with_availability_and_get_their_defaults(
    bridge: MqttBridge, broker: FakeBroker
) -> None:
    fader, led = number(), MQTTSwitch("xtouch", "strip_1_mute_led", "Mute LED")
    connections: list[bool] = []
    bridge.on_connection = connections.append
    await bridge.set_entities({fader: "0", led: "OFF"})

    await start(bridge)

    discovery = json.loads(broker.retained["homeassistant/number/xtouch/strip_1_fader/config"])
    assert discovery["availability_topic"] == AVAILABILITY
    assert discovery["origin"]["name"] == "xtouch-daemon"
    assert discovery["command_topic"] == "homeassistant/number/xtouch/strip_1_fader/set"
    assert broker.retained[AVAILABILITY] == "offline"
    # no retained state: the defaults, which come back to the entities
    await until(lambda: fader.state == "0" and led.state == "OFF")
    assert broker.retained["homeassistant/number/xtouch/strip_1_fader/state"] == "0"
    assert connections == [True]
    client = broker.connected[0]
    assert client.options["password"] == "secret"
    assert client.options["will"].topic == AVAILABILITY


async def test_retained_states_restore_what_home_assistant_set(bridge: MqttBridge, broker: FakeBroker) -> None:
    fader = number()
    broker.retained["homeassistant/number/xtouch/strip_1_fader/state"] = "42"
    seen: list[str | None] = []
    bridge.watch(fader, lambda entity: seen.append(entity.state))
    await bridge.set_entities({fader: "0"})

    await start(bridge)

    assert fader.state == "42"
    assert "0" not in seen
    assert seen[-1] == "42"
    assert ("homeassistant/number/xtouch/strip_1_fader/state", "0", True) not in broker.published


async def test_a_command_of_home_assistant_changes_the_entity(bridge: MqttBridge, broker: FakeBroker) -> None:
    fader = number()
    changes: list[MQTTEntity] = []
    bridge.watch(fader, changes.append)
    await bridge.set_entities({fader: "0"})
    await start(bridge)

    broker.publish("homeassistant/number/xtouch/strip_1_fader/set", "55")
    await until(lambda: fader.state == "55")

    assert changes[-1] is fader
    bridge.unwatch(fader)
    bridge.unwatch(fader)


async def test_events_are_neither_retained_nor_followed(bridge: MqttBridge, broker: FakeBroker) -> None:
    event = MQTTEvent("xtouch", "strip_1_buttons", "Buttons", ["mute_pressed"])
    await bridge.set_entities({event: None})
    await start(bridge)

    await event.trigger("mute_pressed")

    topic = "homeassistant/event/xtouch/strip_1_buttons/state"
    assert topic not in broker.connected[0].subscriptions
    assert (topic, json.dumps({"event_type": "mute_pressed"}), False) in broker.published


async def test_availability_follows_the_device(bridge: MqttBridge, broker: FakeBroker) -> None:
    await bridge.set_available(True)  # not connected yet: kept for the connect
    await start(bridge)
    assert broker.retained[AVAILABILITY] == "online"

    await bridge.set_available(False)
    assert broker.retained[AVAILABILITY] == "offline"


async def test_without_connection_states_are_dropped(bridge: MqttBridge, broker: FakeBroker) -> None:
    fader = number()
    await bridge.set_entities({fader: "0"})

    await bridge.set_state(fader, "10")
    await bridge.set_attributes(fader, "{}")
    await bridge.close()

    assert broker.published == []
    assert not bridge.connected


async def test_a_publish_that_fails_is_left_to_the_reconnect(
    bridge: MqttBridge, broker: FakeBroker, caplog: pytest.LogCaptureFixture
) -> None:
    fader = number()
    await bridge.set_entities({fader: "0"})
    await start(bridge)
    caplog.set_level(logging.DEBUG)

    broker.connected[0].fail_publish = True
    await bridge.set_state(fader, "10")
    await bridge.close()

    assert "Can't publish the state of number.xtouch_strip_1_fader" in caplog.text


async def test_attributes_are_published_retained(bridge: MqttBridge, broker: FakeBroker) -> None:
    fader = number()
    await bridge.set_entities({fader: "0"})
    await start(bridge)

    await bridge.set_attributes(fader, '{"a": 1}')

    assert broker.retained["homeassistant/number/xtouch/strip_1_fader/attributes"] == '{"a": 1}'


async def test_new_entities_replace_the_old_ones_and_removed_ones_leave_home_assistant(
    bridge: MqttBridge, broker: FakeBroker
) -> None:
    old_fader, encoder = number(), number("strip_1_encoder")
    event = MQTTEvent("xtouch", "strip_1_buttons", "Buttons", ["mute_pressed"])
    await bridge.set_entities({old_fader: "0", encoder: "0", event: None})
    await start(bridge)
    broker.publish("homeassistant/number/xtouch/strip_1_fader/set", "30")
    await until(lambda: old_fader.state == "30")

    new_fader = number()
    await bridge.set_entities({new_fader: "0"})
    await until(lambda: bridge.ready and new_fader.state == "30")

    assert "homeassistant/number/xtouch/strip_1_encoder/config" not in broker.retained
    assert "homeassistant/event/xtouch/strip_1_buttons/config" not in broker.retained
    assert "homeassistant/number/xtouch/strip_1_encoder/set" not in broker.connected[0].subscriptions
    # the state stays on the broker, for when the strip comes back
    assert broker.retained["homeassistant/number/xtouch/strip_1_encoder/state"] == "0"


async def test_a_preview_removes_nothing_and_going_back_to_the_file_restores_the_entities(
    bridge: MqttBridge, broker: FakeBroker
) -> None:
    fader, encoder = number(), number("strip_1_encoder")
    await bridge.set_entities({fader: "0", encoder: "0"})
    await start(bridge)
    broker.publish("homeassistant/number/xtouch/strip_1_fader/set", "30")
    await until(lambda: fader.state == "30")

    # the preview has another strip: the entities of the file stay in Home Assistant, but nothing drives them
    desk = number("desk_fader")
    await bridge.set_entities({desk: "0"}, preview=True)
    await until(lambda: bridge.ready and desk.state == "0")
    assert "homeassistant/number/xtouch/strip_1_fader/config" in broker.retained
    assert "homeassistant/number/xtouch/strip_1_encoder/config" in broker.retained
    assert broker.retained["homeassistant/number/xtouch/strip_1_fader/state"] == "30"
    assert "homeassistant/number/xtouch/strip_1_fader/set" not in broker.connected[0].subscriptions
    assert bridge.entity_count == 1
    # a second step of the preview without the desk does not remove it either
    await bridge.set_entities({}, preview=True)
    assert "homeassistant/number/xtouch/desk_fader/config" in broker.retained

    # back to the file (new entities, as a new mixer makes them): as they were
    fader, encoder = number(), number("strip_1_encoder")
    await bridge.set_entities({fader: "0", encoder: "0"})
    await until(lambda: bridge.ready and fader.state == "30")
    assert encoder.state == "0"
    # the entity only the preview had is gone, with the state it left on the broker
    assert "homeassistant/number/xtouch/desk_fader/config" not in broker.retained
    assert "homeassistant/number/xtouch/desk_fader/state" not in broker.retained
    assert "homeassistant/number/xtouch/strip_1_fader/config" in broker.retained


async def test_entities_of_the_file_that_a_preview_dropped_go_when_the_next_file_drops_them(
    bridge: MqttBridge, broker: FakeBroker
) -> None:
    fader, encoder = number(), number("strip_1_encoder")
    await bridge.set_entities({fader: "0", encoder: "0"})
    await start(bridge)
    await bridge.set_entities({number(): "0"}, preview=True)
    await until(lambda: bridge.ready)

    # the saved file has no encoder: it leaves Home Assistant, its state stays (as with any reload)
    fader = number()
    await bridge.set_entities({fader: "0"})
    await until(lambda: bridge.ready)

    assert "homeassistant/number/xtouch/strip_1_encoder/config" not in broker.retained
    assert broker.retained["homeassistant/number/xtouch/strip_1_encoder/state"] == "0"
    assert "homeassistant/number/xtouch/strip_1_fader/config" in broker.retained


async def test_entities_set_while_not_connected_are_announced_on_connect(
    bridge: MqttBridge, broker: FakeBroker
) -> None:
    await bridge.set_entities({number("strip_1_encoder"): "0"}, preview=True)
    await bridge.set_entities({number(): "0"})
    await start(bridge)

    assert "homeassistant/number/xtouch/strip_1_fader/config" in broker.retained
    assert "homeassistant/number/xtouch/strip_1_encoder/config" not in broker.retained


async def test_entities_of_other_layouts_stay_in_home_assistant(bridge: MqttBridge, broker: FakeBroker) -> None:
    fader, encoder = number(), number("strip_1_encoder")
    await bridge.set_entities({fader: "0", encoder: "0"})
    await start(bridge)
    await until(lambda: bridge.ready)

    await bridge.set_entities({fader: "0"}, keep=frozenset({encoder.unique_id}))
    await until(lambda: bridge.ready)

    # announced still, but not followed while its layout is not shown
    assert "homeassistant/number/xtouch/strip_1_encoder/config" in broker.retained
    assert "homeassistant/number/xtouch/strip_1_encoder/set" not in broker.connected[0].subscriptions


async def test_a_lost_broker_is_reported_once_and_connected_again(
    bridge: MqttBridge, broker: FakeBroker, caplog: pytest.LogCaptureFixture
) -> None:
    fader = number()
    await bridge.set_entities({fader: "0"})
    connections: list[bool] = []
    bridge.on_connection = connections.append
    await start(bridge)
    await bridge.set_available(True)

    assert (bridge.error, bridge.entity_count) == (None, 1)
    broker.refuse = 3
    broker.disconnect()
    await until(lambda: bridge.error == "Connection refused")
    await until(lambda: connections == [True, False, True])
    await until(lambda: bridge.ready)
    # connected again: the error is history
    assert bridge.error is None

    # the last will marked the entities unavailable while it was gone
    assert ("xtouch-daemon/xtouch/availability", "offline", True) in broker.published
    assert broker.retained[AVAILABILITY] == "online"
    assert caplog.text.count("Lost the MQTT broker") == 1


async def test_a_failing_handler_is_logged_and_others_go_on(
    bridge: MqttBridge, broker: FakeBroker, caplog: pytest.LogCaptureFixture
) -> None:
    fader, other = number(), number("strip_2_fader")

    def broken(entity: MQTTEntity) -> None:
        raise RuntimeError("broken watcher")

    await bridge.set_entities({fader: "0", other: "0"})
    await start(bridge)
    bridge.watch(fader, broken)

    broker.publish("homeassistant/number/xtouch/strip_1_fader/set", "5")
    broker.publish("homeassistant/number/xtouch/strip_2_fader/set", "6")
    await until(lambda: other.state == "6")

    assert "broken watcher" in caplog.text


async def test_unknown_topics_and_old_sync_tokens_are_ignored(bridge: MqttBridge, broker: FakeBroker) -> None:
    await start(bridge)

    broker.connected[0].subscriptions.add("something/else")
    broker.publish("something/else", "x")
    broker.publish(bridge.sync_topic, "an old token")
    await asyncio.sleep(0.01)

    assert bridge.ready


async def test_closing_marks_the_entities_unavailable(bridge: MqttBridge, broker: FakeBroker) -> None:
    await bridge.set_available(True)
    await start(bridge)

    await bridge.close()
    assert broker.retained[AVAILABILITY] == "offline"

    # a broken connection can't do that, the last will does it
    broker.connected[0].fail_publish = True
    await bridge.close()


def test_the_device_names_the_daemon() -> None:
    bridge = MqttBridge(MqttConfig(host="broker", device_name="Desk", namespace="desk"))

    assert bridge.device.name == "Desk"
    assert bridge.device.identifiers == ["xtouch_daemon_desk"]
    assert bridge.availability_topic == "xtouch-daemon/desk/availability"


# -- the password -------------------------------------------------------------------------------------------------


def test_the_password_can_come_from_a_file_or_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "password"
    secret.write_text("from file\n")
    monkeypatch.setenv("XTOUCH_MQTT_PASSWORD", "from env")

    assert MqttConfig(host="b", password_file=secret).resolve_password() == "from file"
    assert MqttConfig(host="b", password_env="XTOUCH_MQTT_PASSWORD").resolve_password() == "from env"
    assert MqttConfig(host="b").resolve_password() is None
    monkeypatch.setenv("HOME", str(tmp_path))
    assert MqttConfig(host="b", password_file=Path("~/password")).resolve_password() == "from file"


def test_a_password_that_is_not_there_stops_the_bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XTOUCH_MISSING", raising=False)

    with pytest.raises(ConfigError, match="can't read"):
        MqttBridge(MqttConfig(host="b", password_file=tmp_path / "missing"))
    with pytest.raises(ConfigError, match="XTOUCH_MISSING is not set"):
        MqttBridge(MqttConfig(host="b", password_env="XTOUCH_MISSING"))


def test_the_password_is_not_shown() -> None:
    assert "secret" not in repr(CONFIG)
    assert "secret" not in str(CONFIG.model_dump())
