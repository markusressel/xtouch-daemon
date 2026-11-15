import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.fake_mqtt import FakeBroker
from xtouch_daemon.config import MqttConfig
from xtouch_daemon.gui.domain import broker
from xtouch_daemon.gui.domain.broker import explain, header_status, live_status, try_broker
from xtouch_daemon.gui.domain.status import Tone
from xtouch_daemon.live import MqttState, Snapshot


def snapshot(mqtt: bool | None, state: MqttState | None = None) -> Snapshot:
    return Snapshot("abc", True, True, mqtt, (), state)


def state(connected: bool = True, ready: bool = True, error: str | None = None) -> MqttState:
    return MqttState("broker:1883", "me", connected, ready, error, 1)


def test_errors_say_what_to_check():
    # the words of MQTT 3.1.1 and of MQTT 5
    for error in (
        "[code:5] Connection refused: Not authorised",
        "[code:4] Connection refused: Bad username or password",
        "[code:135] Not authorized",
        "[code:134] Bad user name or password",
    ):
        assert explain(error).short == "not authorized", error
    assert explain("[Errno 111] Connection refused").short == "refused"
    assert explain("[Errno -2] Name or service not known").short == "unknown host"
    assert explain("[Errno -3] Temporary failure in name resolution").short == "unknown host"
    assert explain("timed out").short == "unreachable"
    assert explain("[Errno 113] No route to host").short == "unreachable"
    assert explain("something else") == broker.Explanation("something else", "")


def test_the_page_tells_how_the_daemon_is_connected():
    assert live_status(None).text == "unknown"
    # the daemon reads [mqtt] only when it starts
    assert live_status(snapshot(None)).text == "not in use"
    assert "restart" in live_status(snapshot(None)).tip

    good = live_status(snapshot(True, state()))
    assert (good.text, good.tone) == ("connected", Tone.GOOD)
    assert good.tip == "Connected to the MQTT broker broker:1883 as me, 1 entity in Home Assistant."
    assert live_status(snapshot(True, state(ready=False))).text == "syncing"
    assert live_status(snapshot(False, state(connected=False, ready=False))).text == "connecting"
    bad = live_status(snapshot(False, state(connected=False, ready=False, error="[code:135] Not authorized")))
    assert (bad.text, bad.tone) == ("not authorized", Tone.BAD)
    assert "[code:135] Not authorized" in bad.tip
    assert "tries again" in bad.tip
    # without a hint for errors it does not know
    odd = live_status(snapshot(False, MqttState("broker:1883", None, False, False, "odd", 2)))
    assert odd.tip == f"Can't connect to the MQTT broker broker:1883: odd. {broker.RETRY}"

    # an older daemon only tells whether it is connected
    assert live_status(snapshot(True)).text == "connected"
    assert live_status(snapshot(False)).tone == Tone.WARN


def test_the_header_names_home_assistant_while_the_daemon_uses_it():
    assert header_status(None) is None
    assert header_status(snapshot(None)) is None
    good = header_status(snapshot(True, state()))
    assert good is not None
    assert good.text == "Home Assistant"
    bad = header_status(snapshot(False, state(connected=False, ready=False, error="[Errno 111] Connection refused")))
    assert bad is not None
    assert (bad.text, bad.tone) == ("Home Assistant · refused", Tone.BAD)


async def test_the_settings_are_tried_once():
    fake = FakeBroker()
    config = MqttConfig(host="broker", username="me", password="secret")  # type: ignore[arg-type]
    status = await try_broker(config, fake.client)
    assert (status.text, status.tone) == ("Connected to broker:1883 as me: these settings work.", Tone.GOOD)
    (client,) = fake.clients
    assert (client.options["hostname"], client.options["password"]) == ("broker", "secret")
    # and disconnected again
    assert not client.connected

    fake.refuse = 1
    status = await try_broker(config, fake.client)
    assert (status.text, status.tone) == ("Can't connect to broker:1883 as me: Connection refused.", Tone.BAD)
    assert "is the broker running" in status.tip


async def test_a_broker_that_does_not_answer_is_given_up_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(broker, "TEST_TIMEOUT", 0.01)

    class Silent:
        def __init__(self, **options: Any) -> None:
            pass

        async def __aenter__(self) -> None:
            await asyncio.sleep(10)

        async def __aexit__(self, *exc: object) -> None:
            pass

    status = await try_broker(MqttConfig(host="broker"), Silent)
    assert status.text == "Can't connect to broker:1883: no answer in 0.01 s."
    assert "check `host`" in status.tip


async def test_a_password_that_is_not_there_is_reported(tmp_path: Path):
    status = await try_broker(MqttConfig(host="broker", password_file=tmp_path / "missing"), FakeBroker().client)
    assert status.tone == Tone.BAD
    assert "can't read" in status.tip
