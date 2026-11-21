"""
The entities of Home Assistant in the GUI: suggestions, what an unset option does by the domain, the status of the
connection, the test of the settings, and the entities the window keeps.
"""

import dataclasses

import pytest
from pydantic import SecretStr

from tests.support.homeassistant import FakeHomeAssistant, hass_config
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.gui.domain.connections import connections
from xtouch_daemon.gui.domain.entities import (
    DEFAULT_ICON,
    STALE_AFTER,
    EntityCache,
    Tried,
    attribute_suggestions,
    data_text,
    domain_icon,
    entity_suggestion,
    explain,
    live_status,
    parse_data,
    section_config,
    try_home_assistant,
    value_placeholder,
    value_text,
    why_no_entities,
)
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.homeassistant.client import Fetched, fetch
from xtouch_daemon.homeassistant.states import EntityState
from xtouch_daemon.live.messages import HomeAssistantState, Snapshot

LIGHT = EntityState("light.desk", "on", {"friendly_name": "Desk lamp", "brightness": 180})
NUMBER = EntityState("number.amp", "30", {"friendly_name": "Amp", "min": 10, "max": 60})
SENSOR = EntityState("sensor.temp", "21.5", {"unit_of_measurement": "°C"})
CONNECTED = HomeAssistantState("http://ha.test:8123", True, True, None, 120, 3, "2026.11.0")


def test_the_section_is_read_from_the_editor():
    assert section_config(None) is None
    config = section_config({"url": "http://ha.test:8123", "token": "t"})
    assert isinstance(config, HomeAssistantConfig)
    assert config.url == "http://ha.test:8123"
    assert section_config({"url": "http://ha.test:8123"}) == (
        "needs token, token_file or token_env: a long-lived access token of Home Assistant"
    )
    assert str(section_config({"token": "t"})).startswith("url: ")


def test_an_entity_is_suggested_with_its_name_and_state():
    assert entity_suggestion(LIGHT).value == "light.desk"
    assert entity_suggestion(LIGHT).detail == "Desk lamp"
    assert entity_suggestion(LIGHT).origin == "on"
    # without a name, its id only; a number with its unit
    assert entity_suggestion(SENSOR).detail == ""
    assert entity_suggestion(SENSOR).origin == "21.5 °C"
    gone = entity_suggestion(EntityState("switch.fan", "unavailable", {"unit_of_measurement": "W"}))
    assert gone.origin == "unavailable"
    assert not gone.present


def test_the_attributes_of_an_entity_are_suggested_with_their_values():
    found = attribute_suggestions(EntityState("light.x", "on", {"friendly_name": "X", "brightness": 3, "modes": ["a"]}))
    assert [(s.value, s.origin) for s in found] == [("brightness", "3"), ("modes", '["a"]')]
    assert attribute_suggestions(None) == ()
    assert value_text("x" * 50) == "x" * 39 + "…"


def test_an_entity_has_the_icon_of_its_domain():
    assert domain_icon("light.desk") == "lightbulb"
    assert domain_icon("strange.thing") == DEFAULT_ICON


@pytest.mark.parametrize(
    ("name", "table", "entity", "expected"),
    [
        ("attribute", {"entity": "light.desk"}, None, "brightness, of a light"),
        ("min", {"entity": "light.desk"}, None, "0, of a light"),
        ("max", {"entity": "light.desk"}, None, "255, of a light"),
        ("service", {"entity": "light.desk"}, None, "light.turn_on, of a light"),
        ("data", {"entity": "light.desk"}, None, '{ brightness = "{value}" }, of a light'),
        # a number tells its own range
        ("max", {"entity": "number.amp"}, NUMBER, "60, the entity's max"),
        ("attribute", {"entity": "number.amp"}, None, "none: the state"),
        # another attribute: nothing of the domain
        ("min", {"entity": "light.desk", "attribute": "color_temp"}, None, "0"),
        ("max", {"entity": "light.desk", "attribute": "color_temp"}, None, "100"),
        (
            "service",
            {"entity": "light.desk", "attribute": "color_temp"},
            None,
            "none: set one, nothing sets this of a light by itself",
        ),
        ("data", {"entity": "sensor.temp"}, None, 'none, e.g. { value = "{value}" }'),
        ("attribute", {"entity": "sensor.temp"}, None, "none: the state"),
        # no entity yet
        ("min", {"entity": ""}, None, "by its domain"),
        ("format", {"entity": "light.desk"}, None, None),
        ("format", {"entity": ""}, None, None),
    ],
)
def test_an_unset_option_says_what_the_domain_does(
    name: str, table: dict[str, str], entity: EntityState | None, expected: str | None
):
    assert value_placeholder(name, table, entity) == expected


def test_data_is_typed_as_an_inline_table():
    assert data_text({"brightness_pct": 50, "name": "x"}) == '{brightness_pct = 50, name = "x"}'
    assert data_text(None) == ""
    assert data_text("broken") == "broken"
    assert parse_data('{ brightness_pct = 50, level = "{value}" }') == {"brightness_pct": 50, "level": "{value}"}
    assert parse_data("  ") is None
    # not a table: the text, whose problem says so
    assert parse_data("{ brightness_pct = ") == "{ brightness_pct ="
    assert parse_data("50") == "50"


@pytest.mark.parametrize(
    ("error", "short"),
    [
        ("Home Assistant refused the token (Invalid access token or password)", "bad token"),
        ("needs token, token_file or token_env: a long-lived access token of Home Assistant", "no token"),
        ("this is no WebSocket API of Home Assistant (it sent 'hello')", "no Home Assistant"),
        ("Home Assistant did not answer within 10 s", "no answer"),
        ("can't connect to ws://ha.test:8123/api/websocket: Connection refused", "unreachable"),
        ("something else", "error"),
    ],
)
def test_an_error_says_what_to_check(error: str, short: str):
    assert explain(error).short == short


def test_the_daemons_connection_shows():
    assert live_status(None).text == "unknown"
    snapshot = Snapshot("x", True, True, None, ())
    assert live_status(snapshot).text == "not in use"
    status = live_status(dataclasses.replace(snapshot, homeassistant=CONNECTED))
    assert status == Status(
        "connected",
        Tone.GOOD,
        "Connected to Home Assistant 2026.11.0 at http://ha.test:8123: 120 entities, 3 of them on the device.",
    )
    syncing = dataclasses.replace(CONNECTED, synced=False, version=None)
    assert live_status(dataclasses.replace(snapshot, homeassistant=syncing)).text == "syncing"
    connecting = dataclasses.replace(CONNECTED, connected=False, synced=False)
    assert live_status(dataclasses.replace(snapshot, homeassistant=connecting)).tone == Tone.WARN
    refused = dataclasses.replace(connecting, error="Home Assistant refused the token (Invalid)")
    status = live_status(dataclasses.replace(snapshot, homeassistant=refused))
    assert (status.text, status.tone) == ("bad token", Tone.BAD)
    # a refused token is not tried again
    assert "tries again" not in status.tip
    down = dataclasses.replace(connecting, error="can't connect to ws://ha.test:8123/api/websocket: refused")
    assert "tries again" in live_status(dataclasses.replace(snapshot, homeassistant=down)).tip


def test_the_connection_to_the_api_is_one_of_the_daemons():
    snapshot = Snapshot("x", True, True, None, ())
    assert [found.name for found in connections(snapshot, "X-Touch")] == ["X-Touch", "Sound server"]
    found = connections(dataclasses.replace(snapshot, homeassistant=CONNECTED), "X-Touch")
    assert found[-1].name == "Home Assistant API"
    assert found[-1].settings == "homeassistant"
    assert found[-1].status.text == "connected"


async def test_the_settings_are_tried_once():
    home = FakeHomeAssistant()
    home.set("light.desk", "on", friendly_name="Desk lamp")

    async def read(config: HomeAssistantConfig) -> Fetched:
        return await fetch(config, home.connect)

    tried = await try_home_assistant(hass_config(), read)
    assert tried.status == Status("Connected to Home Assistant 2026.11.0 at http://ha.test:8123: 1 entity.", Tone.GOOD)
    assert tried.entities is not None
    assert [entity.entity_id for entity in tried.entities] == ["light.desk"]

    refused = await try_home_assistant(hass_config(token="wrong"), read)
    assert refused.status.tone == Tone.BAD
    assert refused.status.tip.startswith("Home Assistant does not take the token.")
    assert refused.entities is None
    home.refuse = 1
    unreachable = await try_home_assistant(hass_config(), read)
    assert "Connection refused" in unreachable.status.text
    assert unreachable.status.tip.startswith("Nothing answers at `url`")
    assert unreachable.error is not None


async def test_a_token_that_cant_be_read_says_so():
    async def unreadable(config: HomeAssistantConfig) -> Fetched:
        raise ConfigError("homeassistant.token_file: /nowhere does not exist")

    tried = await try_home_assistant(hass_config(), unreadable)
    assert tried.status.text == "Can't connect: homeassistant.token_file: /nowhere does not exist."


async def test_a_version_unknown_is_left_out():
    async def nameless(config: HomeAssistantConfig) -> Fetched:
        return Fetched("", ())

    tried = await try_home_assistant(hass_config(), nameless)
    assert tried.status.text == "Connected to Home Assistant at http://ha.test:8123: 0 entities."


def test_the_entities_are_read_again_for_other_settings_or_later():
    cache = EntityCache()
    config = hass_config()
    assert cache.wants(config, 0)
    cache.start(config)
    # one read at a time
    assert not cache.wants(config, 0)
    assert why_no_entities(config, cache, None) == "Reading the entities of Home Assistant…"
    assert cache.done(config, Tried(Status("ok", Tone.GOOD), (LIGHT,)), 10)
    assert cache.entity("light.desk") == LIGHT
    assert cache.entity(None) is None
    assert why_no_entities(config, cache, None) == ""
    assert not cache.wants(config, 10 + STALE_AFTER - 1)
    assert cache.wants(config, 10, again=True)
    assert cache.wants(config, 10 + STALE_AFTER)
    other = HomeAssistantConfig(url="http://other:8123", token=SecretStr("t"))
    assert cache.wants(other, 11)
    # the entities are of other settings
    assert why_no_entities(other, cache, None) == ""

    cache.done(config, Tried(Status("no", Tone.BAD), None, "can't connect to ws://x: Connection refused"), 20)
    assert cache.entities == ()
    assert why_no_entities(config, cache, None) == (
        "No suggestions: Nothing answers at `url`: check the address and that Home Assistant runs."
    )
    # the daemon reaches it
    assert why_no_entities(config, cache, CONNECTED).endswith(
        "The daemon is connected, with 120 entities: the window may lack the token it has."
    )
    cache.done(config, Tried(Status("x", Tone.BAD), None, "odd"), 30)
    assert why_no_entities(config, cache, None) == "No suggestions: odd"
    cache.done(config, Tried(Status("ok", Tone.GOOD), ()), 40)
    assert why_no_entities(config, cache, None) == "No suggestions: Home Assistant has no entities."


def test_why_there_are_no_suggestions_without_settings():
    cache = EntityCache()
    assert why_no_entities(None, cache, None).startswith("No suggestions: add `[homeassistant]`")
    assert why_no_entities("url: missing", cache, None) == (
        "No suggestions: the settings of Home Assistant have a problem (url: missing)."
    )


def test_a_failed_read_leaves_no_old_entities():
    cache = EntityCache()
    config = hass_config()
    cache.done(config, Tried(Status("ok", Tone.GOOD), (LIGHT,)), 0)
    cache.done(config, Tried(Status("no", Tone.BAD), None, "gone"), 1)
    assert cache.entity("light.desk") is None
    assert cache.error == "gone"
    # a test with an error of its own: its text
    cache.done(config, Tried(Status("Can't", Tone.BAD)), 2)
    assert cache.error == "Can't"
