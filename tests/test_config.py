from pathlib import Path

import pytest
from pydantic import ValidationError

from xtouch_daemon.config import (
    STRIP_MODELS,
    STRIP_TYPES,
    AppsStripConfig,
    AutoStripConfig,
    BehaviorConfig,
    Config,
    ConfigError,
    DeviceStripConfig,
    EmptyStripConfig,
    Problem,
    color_of,
    default_config_path,
    example_config,
    load_config,
    parse_config,
    problems_of,
)
from xtouch_daemon.protocol import Color

FULL = """
[device]
name = "X-Touch-Ext"

[behavior]
max_volume = 120
encoder_step = 2
reset_volume = 80
meters = false
auto_hold = 2.5
ignore = ["speech-dispatcher", "notify"]

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
device = "alsa_output.analog"
label = "Speaker"
color = "cyan"
select = false

[[strip]]
type = "input"

[[strip]]
type = "apps"
match = ["discord", "mumble"]
label = "VoIP"
color = "off"
meter = false

[[strip]]
type = "empty"
"""


def test_reads_every_option():
    config = parse_config(FULL)

    assert config.behavior.max_volume == 120
    assert config.behavior.encoder_step == 2
    assert config.behavior.reset_volume == 80
    assert not config.behavior.meters
    assert config.behavior.auto_hold == 2.5
    assert config.behavior.ignore == ("speech-dispatcher", "notify")
    assert config.aliases == {"WEBRTC VoiceEngine": "Discord"}
    assert config.strips == (
        DeviceStripConfig(type="output", device="alsa_output.analog", label="Speaker", color="cyan", select=False),
        DeviceStripConfig(type="input"),
        AppsStripConfig(type="apps", match=("discord", "mumble"), label="VoIP", color="off", meter=False),
        EmptyStripConfig(type="empty"),
    )


def test_strips_that_are_not_configured_are_auto():
    strips = parse_config(FULL).all_strips()
    assert len(strips) == 8
    assert strips[4:] == (AutoStripConfig(type="auto"),) * 4
    assert len(Config().all_strips()) == 8


def test_an_empty_file_is_the_defaults():
    config = parse_config("")
    assert config == Config()
    assert config.device.name == "X-Touch-Ext"
    assert config.behavior.max_volume == 100


def test_colors_have_their_lcd_color():
    assert color_of("off") == Color.BLACK
    assert color_of("cyan") == Color.CYAN
    assert color_of("white") == Color.WHITE


def test_the_example_configuration_is_valid():
    config = parse_config(example_config())
    assert len(config.all_strips()) == 8


def errors_of(text: str) -> str:
    with pytest.raises(ConfigError) as error:
        parse_config(text, "config.toml")
    return str(error.value)


def test_invalid_toml_names_the_file():
    assert errors_of("[device").startswith("config.toml is not valid TOML: ")


@pytest.mark.parametrize(
    ("text", "location"),
    [
        ("[behavior]\nmax_volume = 200", "behavior.max_volume"),
        ("[behavior]\nmax_volume = 99", "behavior.max_volume"),
        ("[behavior]\nencoder_step = 0", "behavior.encoder_step"),
        ("[behavior]\nreset_volume = 151", "behavior.reset_volume"),
        ("[behavior]\nreset_volume = 120", "behavior"),
        ("[behavior]\nauto_hold = -1", "behavior.auto_hold"),
        # a typo in an option name
        ("[behavior]\nmax_volum = 120", "behavior.max_volum"),
        ('[aliases]\nBrave = "Browser!!"', "aliases.Brave"),
        ('[[strip]]\ntype = "auto"\n[[strip]]\ntype = "output"\nlabel = "Lautsprecher"', "strip[2].label"),
        ('[[strip]]\ntype = "output"\nlabel = "Grüße"', "strip[1].label"),
        ('[[strip]]\ntype = "auto"\ncolor = "pink"', "strip[1].color"),
        ('[[strip]]\ntype = "apps"\nmatch = []\nlabel = "x"', "strip[1].match"),
        ('[[strip]]\ntype = "apps"\nmatch = ["discord"]', "strip[1].label"),
        ('[[strip]]\ntype = "fader"', "strip[1]"),
        ('[[strip]]\ntype = "empty"\ncolor = "red"', "strip[1].color"),
        ('[[strip]]\ntype = "auto"\n' * 9, "strip"),
    ],
)
def test_errors_name_the_option(text: str, location: str):
    message = errors_of(text)
    assert message.startswith("config.toml has errors:\n")
    assert f"\n  {location}: " in message


def test_a_blank_pattern_would_match_every_application():
    message = errors_of('[[strip]]\ntype = "apps"\nmatch = ["discord", " "]\nlabel = "VoIP"')
    assert "strip[1].match: an empty pattern would match every application" in message


def test_a_list_at_the_top_level_names_its_position():
    # pydantic never reports one for the top-level table of a TOML file
    assert Problem((0, "label"), "", "").location == "0.label"
    assert Problem(("strip", 1, "match", 0), "", "").location == "strip[2].match[1]"


def test_problems_name_the_place_in_the_toml_data():
    with pytest.raises(ValidationError) as error:
        Config.model_validate({"aliases": {"output": "too long"}, "strip": [{"type": "apps", "match": ["x"]}]})

    assert [(problem.path, problem.kind) for problem in problems_of(error.value)] == [
        # an alias for an application named like a strip type is not a strip type
        (("aliases", "output"), "string_too_long"),
        (("strip", 0, "label"), "missing"),
    ]
    assert str(problems_of(error.value)[1]) == "strip[1].label: Field required"


def test_the_strip_types_are_the_ones_of_the_models():
    assert (DeviceStripConfig, AppsStripConfig, AutoStripConfig, EmptyStripConfig) == STRIP_MODELS
    assert STRIP_TYPES == ("output", "input", "apps", "auto", "empty")


def test_the_docstrings_of_the_options_are_their_descriptions():
    assert BehaviorConfig.model_fields["encoder_step"].description == "Percent per step of an encoder."


def test_the_default_path_follows_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "xtouch-daemon" / "config.toml"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_config_path() == tmp_path / ".config" / "xtouch-daemon" / "config.toml"


def test_loads_the_file(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(FULL)
    assert load_config(path) == parse_config(FULL)


def test_errors_name_the_file_they_are_in(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[behavior]\nmax_volume = 200")
    with pytest.raises(ConfigError, match=f"^{path} has errors:"):
        load_config(path)


def test_a_missing_file_that_was_asked_for_is_an_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path / "missing.toml")


def test_without_a_file_at_the_default_path_it_is_the_example(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load_config() == parse_config(example_config())

    default_config_path().parent.mkdir()
    default_config_path().write_text("[behavior]\nencoder_step = 3")
    assert load_config().behavior.encoder_step == 3


def test_a_file_that_can_not_be_read_is_an_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="can't read"):
        # a directory
        load_config(tmp_path)


def test_errors_of_checks_across_options_read_as_a_sentence():
    assert errors_of("[behavior]\nreset_volume = 120").endswith(
        "\n  behavior: reset_volume (120) is above max_volume (100)"
    )
