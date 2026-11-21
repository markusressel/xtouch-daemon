"""
The connection to the WebSocket API of Home Assistant, against one in memory; one test against a real WebSocket server
on 127.0.0.1.
"""

import asyncio
import itertools
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from websockets.asyncio.server import ServerConnection, serve

from tests.support.homeassistant import TOKEN, FakeHomeAssistant, FakeTransport, connected, hass_config
from tests.support.tasks import settle
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.homeassistant.client import (
    RECONNECT_DELAYS,
    REQUEST_TIMEOUT,
    HomeAssistant,
    HomeAssistantError,
    TokenRefused,
    describe_entity,
    fetch_entities,
    websocket_connect,
)
from xtouch_daemon.homeassistant.states import EntityState


@pytest.fixture
def home() -> FakeHomeAssistant:
    home = FakeHomeAssistant()
    home.set("light.desk", "on", brightness=128, friendly_name="Desk lamp")
    home.set("sensor.cpu", "12")
    return home


async def test_it_logs_in_and_follows_every_entity(home: FakeHomeAssistant) -> None:
    hass = await connected(home)
    assert home.urls == ["ws://ha.test:8123/api/websocket"]
    assert hass.connected
    assert hass.synced
    assert hass.error is None
    assert hass.version == "2026.11.0"
    assert [entity.entity_id for entity in hass.entities()] == ["light.desk", "sensor.cpu"]
    assert describe_entity(hass.entities()[0]) == "Desk lamp (light.desk)"
    assert describe_entity(hass.entities()[1]) == "sensor.cpu"
    calls: list[str] = []
    hass.watch("sensor.cpu", lambda: calls.append("cpu"))
    assert hass.watched == 1
    home.set("sensor.cpu", "13")
    home.set("light.desk", "off", friendly_name="Desk lamp")
    await settle()
    assert calls == ["cpu"]
    assert hass.state("sensor.cpu") == EntityState("sensor.cpu", "13", {})
    assert hass.state("light.desk") == EntityState("light.desk", "off", {"friendly_name": "Desk lamp"})
    home.set("sensor.new", "1")
    home.remove("sensor.cpu")
    await settle()
    assert calls == ["cpu", "cpu"]
    assert hass.state("sensor.cpu") is None
    assert hass.state("sensor.new") is not None
    await hass.close()
    assert not home.connected


async def test_a_listener_hears_the_states_coming_and_going(home: FakeHomeAssistant) -> None:
    hass = HomeAssistant(home.connect)
    calls: list[str] = []
    listener = lambda: calls.append("desk")  # noqa: E731
    hass.watch("light.desk", listener)
    hass.configure(hass_config())
    await settle()
    assert calls == ["desk"]
    assert hass.ever_synced
    home.disconnect()
    await settle()
    # gone: the entities have no state, until it is back
    assert calls == ["desk", "desk"]
    assert not hass.connected
    assert not hass.synced
    assert hass.ever_synced
    assert hass.state("light.desk") is None
    assert hass.error == "the connection ended"
    hass.unwatch("light.desk", listener)
    hass.unwatch("light.desk", listener)
    assert hass.watched == 0
    await hass.close()


async def test_it_connects_again_waiting_longer_each_time(
    home: FakeHomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    loop = asyncio.get_running_loop()
    times: list[float] = []
    connect = home.connect

    async def timed(url: str) -> FakeTransport:
        times.append(loop.time())
        return await connect(url)

    home.refuse = 3
    hass = HomeAssistant(timed)
    with caplog.at_level(logging.DEBUG):
        hass.configure(hass_config())
        await asyncio.sleep(sum(RECONNECT_DELAYS[:3]) + 0.1)
    assert [round(later - earlier, 6) for earlier, later in itertools.pairwise(times)] == [1.0, 2.0, 5.0]
    assert hass.synced
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    # the first failure is a warning, the others are only details
    assert warnings == [
        "Home Assistant at http://ha.test:8123: can't connect to ws://ha.test:8123/api/websocket: Connection "
        "refused, connecting again in 1 s"
    ]
    # a connection that was there comes back after the shortest wait
    start = loop.time()
    home.disconnect()
    await asyncio.sleep(RECONNECT_DELAYS[0] + 0.01)
    assert hass.synced
    assert round(times[-1] - start, 6) == RECONNECT_DELAYS[0]
    await hass.close()


async def test_a_refused_token_is_not_tried_again(home: FakeHomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    hass = HomeAssistant(home.connect)
    hass.configure(hass_config(token="wrong"))
    await asyncio.sleep(600)
    assert len(home.connections) == 1
    assert not hass.connected
    assert hass.error == "Home Assistant refused the token (Invalid access token or password)"
    assert "create a new long-lived access token" in caplog.text
    # another token: it connects
    hass.configure(hass_config())
    await settle()
    assert hass.synced
    await hass.close()


async def test_a_token_it_cant_read_is_an_error(home: FakeHomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HA_TOKEN", raising=False)
    hass = HomeAssistant(home.connect)
    hass.configure(HomeAssistantConfig(url="http://ha.test:8123", token_env="HA_TOKEN"))
    await settle()
    assert hass.error == "homeassistant.token_env: the environment variable HA_TOKEN is not set"
    assert not home.connections
    await hass.close()


async def test_the_same_section_keeps_the_connection_none_ends_it(home: FakeHomeAssistant) -> None:
    changes: list[bool] = []
    hass = await connected(home)
    hass.on_change = lambda: changes.append(hass.connected)
    hass.configure(hass_config())
    await settle()
    assert len(home.connections) == 1
    assert changes == []
    hass.configure(None)
    await settle()
    assert hass.config is None
    assert not home.connected
    assert not hass.connected
    hass.configure(None)
    await hass.close()


async def test_services_and_states_on_request(home: FakeHomeAssistant) -> None:
    hass = await connected(home)
    await hass.call_service("light.turn_on", {"brightness": 10}, "light.desk")
    await hass.call_service("script.party", None, None)
    assert home.calls == [("light.turn_on", {"brightness": 10}, "light.desk"), ("script.party", {}, None)]
    assert home.connections[0].sent[-1] == {"id": 3, "type": "call_service", "domain": "script", "service": "party"}
    home.failing["light.turn_on"] = "Entity light.desk is unavailable"
    with pytest.raises(HomeAssistantError, match=r"^Entity light.desk is unavailable$"):
        await hass.call_service("light.turn_on", {"brightness": 10}, "light.desk")
    states = await hass.get_states()
    assert [entity.entity_id for entity in states] == ["light.desk", "sensor.cpu"]
    # a Home Assistant that hangs
    home.silent = True
    loop = asyncio.get_running_loop()
    start = loop.time()
    with pytest.raises(HomeAssistantError, match="did not answer within 10 s"):
        await hass.get_states()
    assert loop.time() - start == pytest.approx(REQUEST_TIMEOUT)
    # a request that the end of the connection leaves without an answer
    request = asyncio.create_task(hass.get_states())
    await settle()
    home.disconnect()
    with pytest.raises(HomeAssistantError, match="the connection to Home Assistant ended"):
        await request
    with pytest.raises(HomeAssistantError, match="not connected"):
        await hass.call_service("light.toggle", None, "light.desk")
    await hass.close()


async def test_a_refused_subscription_ends_the_connection(home: FakeHomeAssistant) -> None:
    hass = HomeAssistant(home.connect)
    hass.configure(hass_config())
    await settle()
    transport = home.connections[0]
    transport.push({"id": transport.subscription, "type": "result", "success": False, "error": {"code": "x"}})
    await settle()
    assert hass.error == "x"
    assert transport.closed
    await hass.close()


async def test_entities_it_does_not_have_are_a_warning_once(
    home: FakeHomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    hass = HomeAssistant(home.connect)
    hass.watch("sensor.gone", lambda: None)
    hass.configure(hass_config())
    await settle()
    hass.watch("sensor.gone", lambda: None)
    hass.watch("sensor.also_gone", lambda: None)
    messages = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert messages == [
        "Home Assistant has no entity sensor.gone: its parts show nothing",
        "Home Assistant has no entity sensor.also_gone: its parts show nothing",
    ]
    await hass.close()


async def test_fetching_the_entities_once(home: FakeHomeAssistant) -> None:
    entities = await fetch_entities(hass_config(), home.connect)
    assert [(entity.entity_id, entity.name) for entity in entities] == [
        ("light.desk", "Desk lamp"),
        ("sensor.cpu", "sensor.cpu"),
    ]
    assert not home.connected
    with pytest.raises(TokenRefused, match="refused the token"):
        await fetch_entities(hass_config(token="wrong"), home.connect)
    home.refuse = 1
    with pytest.raises(HomeAssistantError, match="Connection refused"):
        await fetch_entities(hass_config(), home.connect)
    home.silent = True
    with pytest.raises(HomeAssistantError, match="did not answer"):
        await fetch_entities(hass_config(), home.connect)
    with pytest.raises(ConfigError, match="token_file"):
        await fetch_entities(HomeAssistantConfig(url="http://x", token_file=Path("/nonexistent/token")), home.connect)


class Strange(FakeTransport):
    """A server that is no Home Assistant, or one that says unexpected things."""

    def __init__(self, home: FakeHomeAssistant, first: Any) -> None:
        super().__init__(home)
        self.inbox.get_nowait()
        self.inbox.put_nowait(first)


@pytest.mark.parametrize(
    ("first", "problem"),
    [
        ('{"type": "hello"}', "this is no WebSocket API of Home Assistant (it sent 'hello')"),
        ("not json", "Home Assistant sent something that is no JSON: 'not json'"),
        ("[1, 2]", "Home Assistant sent something unexpected: '[1, 2]'"),
    ],
)
async def test_what_is_no_home_assistant(home: FakeHomeAssistant, first: str, problem: str) -> None:
    async def strange(url: str) -> FakeTransport:
        return Strange(home, first)

    with pytest.raises(HomeAssistantError) as raised:
        await fetch_entities(hass_config(), strange)
    assert str(raised.value) == problem


async def test_a_login_that_answers_oddly(home: FakeHomeAssistant) -> None:
    async def odd(url: str) -> FakeTransport:
        transport = FakeTransport(home)
        transport.home = FakeHomeAssistant(token="other")

        async def send(message: str) -> None:
            transport.push({"type": "auth_later"})

        transport.send = send  # type: ignore[method-assign]
        return transport

    with pytest.raises(HomeAssistantError, match=r"did not log in \(it sent 'auth_later'\)"):
        await fetch_entities(hass_config(), odd)


@pytest.mark.looptime(False)
async def test_a_real_websocket_on_the_loopback() -> None:
    async def handler(connection: ServerConnection) -> None:
        await connection.send(json.dumps({"type": "auth_required"}))
        auth = json.loads(await connection.recv())
        if auth["access_token"] != TOKEN:
            await connection.send(json.dumps({"type": "auth_invalid", "message": "no"}))
            return
        await connection.send(json.dumps({"type": "auth_ok", "ha_version": "2026.11.0"}))
        async for message in connection:
            request = json.loads(message)
            state = {"entity_id": "sensor.x", "state": "1", "attributes": {}}
            await connection.send(
                json.dumps({"id": request["id"], "type": "result", "success": True, "result": [state]})
            )

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        config = HomeAssistantConfig(url=f"http://127.0.0.1:{port}", token=SecretStr(TOKEN))
        entities = await fetch_entities(config)
        assert [entity.entity_id for entity in entities] == ["sensor.x"]
        hass = HomeAssistant()
        hass.configure(config)
        for _ in range(200):
            if hass.connected:
                break
            await asyncio.sleep(0.01)
        assert hass.connected
        assert [entity.entity_id for entity in await hass.get_states()] == ["sensor.x"]
        await hass.close()
    # nothing there any more
    with pytest.raises(HomeAssistantError, match="can't connect"):
        await websocket_connect(f"ws://127.0.0.1:{port}/api/websocket")
