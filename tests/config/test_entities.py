"""
Bindings of entities of Home Assistant (`{ entity = "..." }`, `{ service = "..." }`) and the `[homeassistant]` section
they need, as the configuration takes them, and the problems it finds, named by their place.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.bindings import (
    EntityBinding,
    EntityLevelBinding,
    EntityValueBinding,
    ServiceAction,
    describe_part,
    fill_data,
)
from xtouch_daemon.config.buttons import describe_action
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import CustomStripConfig

HOME_ASSISTANT = '[homeassistant]\nurl = "http://homeassistant.local:8123"\ntoken = "abc"\n'

CHANNELS = """\
[channel.out]
type = "output"
device = "speakers"
meter = { entity = "sensor.cpu", min = 30, max = 90 }
color = { entity = "light.desk" }
lcd = { entity = "sensor.temperature" }
select = { press = { service = "light.toggle", entity = "light.desk" }, led = { entity = "light.desk" } }

[channel.lamp]
type = "custom"
label = "Lamp"
fader = { entity = "light.desk" }
encoder = { entity = "light.desk", attribute = "color_temp", service = "light.turn_on", data = { kelvin = "{value}" } }
present = { entity = "light.desk" }
mute = { press = { service = "script.party" } }

[slots]
1 = "out"
2 = "lamp"

[controls.3]
encoder = { entity = "media_player.tv" }
lcd = { entity = "media_player.tv", attribute = "media_title" }
rec = { service = "media_player.media_play_pause", entity = "media_player.tv" }
"""


def test_parts_show_and_set_entities() -> None:
    config = parse_config(HOME_ASSISTANT + CHANNELS)
    out = config.slots.channels["out"]
    assert isinstance(out, BaseStripConfig)
    assert out.meter == EntityLevelBinding(entity="sensor.cpu", min=30, max=90)
    assert out.color == EntityBinding(entity="light.desk")
    assert out.button("select").press == ServiceAction(service="light.toggle", entity="light.desk")
    assert out.button("select").led == EntityBinding(entity="light.desk")
    lamp = config.slots.channels["lamp"]
    assert isinstance(lamp, CustomStripConfig)
    assert lamp.fader == EntityValueBinding(entity="light.desk")
    assert lamp.valued
    assert not lamp.value_bound
    assert list(config.slots.entities) == [
        "channel.out.lcd",
        "channel.out.color",
        "channel.out.meter",
        "channel.out.select.press",
        "channel.out.select.led",
        "channel.lamp.fader",
        "channel.lamp.encoder",
        "channel.lamp.present",
        "channel.lamp.mute.press",
        "controls.3.encoder",
        "controls.3.lcd",
        "controls.3.rec.press",
    ]
    # the bindings with a service's data are hashable as the others
    press = out.button("select").press
    assert isinstance(lamp.encoder, EntityValueBinding)
    assert isinstance(press, ServiceAction)
    assert hash(lamp.encoder) == hash(lamp.encoder.model_copy())
    assert hash(press) == hash(ServiceAction(service="light.toggle", entity="light.desk"))
    assert hash(press) != hash(lamp.encoder)


def test_entities_need_the_section_where_they_are() -> None:
    with pytest.raises(ConfigError) as error:
        parse_config(CHANNELS)
    lines = str(error.value).splitlines()[1:]
    assert lines[:2] == [
        "  channel.out.lcd.entity: an entity of Home Assistant needs a [homeassistant] section",
        "  channel.out.color.entity: an entity of Home Assistant needs a [homeassistant] section",
    ]
    assert "  channel.out.select.press.service: an entity of Home Assistant needs a [homeassistant] section" in lines
    assert "  controls.3.rec.press.service: an entity of Home Assistant needs a [homeassistant] section" in lines
    assert len(lines) == 12


def custom(part: str) -> str:
    return HOME_ASSISTANT + f'[channel.c]\ntype = "custom"\nlabel = "C"\n{part}\n[slots]\n1 = "c"\n'


@pytest.mark.parametrize(
    ("part", "problem"),
    [
        (
            'fader = { entity = "Sensor" }',
            "fader.entity: Sensor is no entity ID (<domain>.<name>, e.g. sensor.cpu_temp)",
        ),
        (
            'fader = { entity = "sensor.x" }',
            "fader: service: nothing sets the state of a sensor entity by itself: set service and data with {value}",
        ),
        (
            'fader = { entity = "light.x", attribute = "color_temp" }',
            "fader: service: nothing sets the attribute color_temp of a light entity by itself",
        ),
        ('fader = { entity = "light.x", data = { a = 1 } }', "fader: data: is for service, which has none here"),
        (
            'fader = { entity = "sensor.x", service = "script.a", data = { a = 1 } }',
            "fader: data: nothing has {value}, so the value goes nowhere",
        ),
        ('fader = { entity = "light.x", min = 5, max = 1 }', "fader: max: 1 is not above min (5)"),
        ('encoder = { entity = "light.x", step = 0 }', "encoder: step: needs to be above 0"),
        ('encoder = { entity = "light.x", min = 0, max = 10, push = 20 }', "encoder: push: 20 is not between"),
        ('encoder = { entity = "light.x", format = "{v}" }', "encoder: format: {v} can't show a value"),
        ('fader = { entity = "light.x", push = 10 }', "fader.push: a fader has no push"),
        ('meter = { entity = "sensor.x", min = 5, max = 5 }', "meter.max: 5 is not above min (5)"),
        ('select = { press = { service = "toggle" } }', "select.press.service: toggle is no service"),
        ('select = { press = { service = "light.toggle", entity = "desk" } }', "select.press.entity: desk is no"),
        (
            'select = { press = { service = "light.turn_on", data = { brightness = "{value}" } } }',
            "select.press: data: {value} is for a fader or an encoder; a press sends the data as it is",
        ),
        ('present = "on"', "present: Input should be a valid dictionary or instance of WatchBinding"),
        ('select = { led = "playing" }', "{ watch = [...] }, or { entity = ... })"),
        ('select = { press = "default" }', "or { service = ... })"),
    ],
)
def test_the_problems_of_entities_name_their_place(part: str, problem: str) -> None:
    with pytest.raises(ConfigError) as error:
        parse_config(custom(part))
    assert problem in str(error.value)


def test_run_takes_the_value_of_an_entity() -> None:
    config = parse_config(custom('fader = { entity = "light.x" }\nselect = { press = { run = "say {value}" } }'))
    assert config.slots.channels["c"].type == "custom"
    with pytest.raises(ConfigError, match="needs a fader or an encoder bound to a value"):
        parse_config(custom('select = { press = { run = "say {value}" } }'))


def test_an_audio_fader_bound_to_an_entity_gives_the_volume_to_the_encoder() -> None:
    text = (
        HOME_ASSISTANT + '[channel.o]\ntype = "output"\nfader = { entity = "light.x" }\nencoder = "balance"\n'
        '[slots]\n1 = "o"\n'
    )
    with pytest.raises(ConfigError, match="with the fader bound to an entity, the encoder sets the volume"):
        parse_config(text)


def test_bindings_of_entities_for_people() -> None:
    assert describe_part(EntityBinding(entity="sensor.x")) == "sensor.x"
    assert describe_part(EntityBinding(entity="sensor.x", attribute="a")) == "sensor.x (a)"
    assert describe_part(EntityLevelBinding(entity="sensor.x", max=50)) == "from 0 to 50, sensor.x"
    assert describe_part(EntityValueBinding(entity="light.x")) == "a value of light.x"
    assert describe_action(ServiceAction(service="light.toggle", entity="light.x")) == "call light.toggle on light.x"
    assert describe_action(ServiceAction(service="script.party")) == "call script.party"


def test_the_value_goes_into_the_data_of_a_service() -> None:
    data = {"a": "{value}", "b": "at {value} %", "c": [1, "{value}"], "d": {"e": "{value}"}, "f": True}
    assert fill_data(data, 3.0) == {"a": 3, "b": "at 3 %", "c": [1, 3], "d": {"e": 3}, "f": True}
    assert fill_data(data, 0.5) == {"a": 0.5, "b": "at 0.5 %", "c": [1, 0.5], "d": {"e": 0.5}, "f": True}


def test_the_section_takes_an_address_and_a_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    section = HomeAssistantConfig.model_validate({"url": "HTTPS://ha.example.org/", "token": "abc"})
    assert section.url == "https://ha.example.org"
    assert section.websocket_url == "wss://ha.example.org/api/websocket"
    assert section.resolve_token() == "abc"
    plain = HomeAssistantConfig.model_validate({"url": "ws://ha:8123/api/websocket", "token": "abc"})
    assert plain.websocket_url == "ws://ha:8123/api/websocket"
    secret = tmp_path / "token"
    secret.write_text(" from file\n")
    assert HomeAssistantConfig(url="http://ha", token_file=secret).resolve_token() == "from file"
    monkeypatch.setenv("XTOUCH_HA_TOKEN", "from env")
    assert HomeAssistantConfig(url="http://ha", token_env="XTOUCH_HA_TOKEN").resolve_token() == "from env"
    with pytest.raises(ConfigError, match=r"homeassistant.token_file: can't read"):
        HomeAssistantConfig(url="http://ha", token_file=tmp_path / "missing").resolve_token()
    for data, problem in [
        ({"url": "homeassistant.local"}, "homeassistant.local is no address of Home Assistant"),
        ({"url": "ftp://ha"}, "ftp://ha is no address"),
        ({"url": "http://"}, "http:// is no address"),
        ({"url": "http://ha"}, "needs token, token_file or token_env"),
        ({"url": "http://ha", "token": "a", "token_env": "B"}, "set only one of token, token_env"),
    ]:
        with pytest.raises(ValidationError, match=problem):
            HomeAssistantConfig.model_validate(data)
