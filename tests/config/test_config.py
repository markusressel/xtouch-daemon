"""
The configuration file: its sections, strips, layouts and their checks.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.support.config import FULL, GAMING, HOME_ASSISTANT, MQTT, errors_of
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import (
    Problem,
    default_config_path,
    example_config,
    load_config,
    parse_config,
    problems_of,
)
from xtouch_daemon.config.layout_strips import InheritStripConfig, VoipStripConfig
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.sections import DeviceConfig, VoipConfig
from xtouch_daemon.config.strips import STRIP_MODELS, STRIP_TYPES, EmptyStripConfig, HomeAssistantStripConfig
from xtouch_daemon.config.values import color_of
from xtouch_daemon.hardware.protocol import Color


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
        DeviceStripConfig(type="output", device=("alsa_output.analog",), label="Speaker", color="cyan", select=False),
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
    assert config.behavior.max_volume == 130


def test_colors_have_their_lcd_color():
    assert color_of("off") == Color.BLACK
    assert color_of("cyan") == Color.CYAN
    assert color_of("white") == Color.WHITE


def test_the_example_configuration_is_valid():
    config = parse_config(example_config())
    assert len(config.all_strips()) == 8


def test_invalid_toml_names_the_file():
    assert errors_of("[device").startswith("config.toml is not valid TOML: ")


@pytest.mark.parametrize(
    ("text", "location"),
    [
        ("[behavior]\nmax_volume = 201", "behavior.max_volume"),
        ("[behavior]\nmax_volume = 99", "behavior.max_volume"),
        ("[behavior]\nencoder_step = 0", "behavior.encoder_step"),
        ("[behavior]\nreset_volume = 201", "behavior.reset_volume"),
        ("[behavior]\nreset_volume = 140", "behavior"),
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
    assert (
        DeviceStripConfig,
        AppsStripConfig,
        AutoStripConfig,
        HomeAssistantStripConfig,
        EmptyStripConfig,
        InheritStripConfig,
        VoipStripConfig,
    ) == STRIP_MODELS
    assert STRIP_TYPES == ("output", "input", "apps", "auto", "homeassistant", "empty", "inherit", "voip")


def test_the_docstrings_of_the_options_are_their_descriptions():
    assert DeviceConfig.model_fields["startup"].description == "How the strips light up after the device connects."


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
    path.write_text("[behavior]\nmax_volume = 201")
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
    assert errors_of("[behavior]\nreset_volume = 140").endswith(
        "\n  behavior: reset_volume (140) is above max_volume (130)"
    )


def test_home_assistant_strips_get_ids_by_their_position_or_their_own():
    config = parse_config(HOME_ASSISTANT + '[[strip]]\ntype = "auto"\n' + HOME_ASSISTANT + 'id = "desk"\n' + MQTT)

    assert [(strip.type, strip_id) for strip, strip_id in config.home_assistant_strips()] == [
        ("homeassistant", "strip_1"),
        ("homeassistant", "desk"),
    ]
    assert config.mqtt is not None
    assert config.mqtt.port == 1883
    assert config.mqtt.discovery_prefix == "homeassistant"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (HOME_ASSISTANT, "strips in Home Assistant need an [mqtt] section"),
        (
            HOME_ASSISTANT + 'id = "strip_2"\n' + HOME_ASSISTANT + MQTT,
            "strips in Home Assistant with the same id: strip_2",
        ),
        (HOME_ASSISTANT + 'id = "Desk Lights"\n' + MQTT, "strip[1].id"),
        (MQTT + 'password = "a"\npassword_env = "B"\n', "set only one of password, password_env"),
        (MQTT + "port = 0\n", "mqtt.port"),
        (HOME_ASSISTANT + "meter = false\n" + MQTT, "strip[1].meter"),
    ],
)
def test_errors_of_home_assistant_strips(text: str, message: str):
    assert message in errors_of(text)


def test_a_device_strip_takes_one_device_or_several() -> None:
    config = parse_config('[[strip]]\ntype = "output"\ndevice = ["bluez_output.*", "Speaker"]\n')
    assert config.strips[0] == DeviceStripConfig(type="output", device=("bluez_output.*", "Speaker"))
    assert DeviceStripConfig.model_validate({"type": "output", "device": "speaker"}).device == ("speaker",)

    with pytest.raises(ConfigError, match="an empty device name"):
        parse_config('[[strip]]\ntype = "output"\ndevice = ["speaker", " "]\n')


def test_a_device_strip_switches_between_two_or_more_profiles_with_rec() -> None:
    analog = '[[strip.profiles]]\nlabel = "Analog"\nprofile = "output:analog-stereo"\n'
    profiles = analog + '[[strip.profiles]]\nlabel = "Digital"\nprofile = "Digital Stereo (IEC958) Output"\n'
    strip = '[[strip]]\ntype = "output"\ndevice = "alsa_output.*"\n'
    config = parse_config(strip + profiles)
    assert [p.label for p in config.strips[0].profiles] == ["Analog", "Digital"]  # type: ignore[union-attr]

    with pytest.raises(ConfigError, match=r"strip\[1\]\.profiles: at least two to switch between"):
        parse_config(strip + analog)
    # its LED shows the profile
    with pytest.raises(ConfigError, match="rec: with profiles its LED shows the profile"):
        parse_config(strip + 'rec = "playing"\n' + profiles)
    with pytest.raises(ConfigError, match=r"strip\[1\]\.profiles\[1\]\.label"):
        parse_config(strip + profiles.replace('"Analog"', '"Analog Stereo"'))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[strip]]\ntype = "auto"\nmin_volume = 130\n', "strip[1]: min_volume (130) is not below max_volume (130)"),
        (
            '[[strip]]\ntype = "apps"\nmatch = ["a"]\nlabel = "A"\nmin_volume = 50\nmax_volume = 40\n',
            "strip[1]: min_volume (50) is not below max_volume (40)",
        ),
        (
            '[[strip]]\ntype = "output"\nmax_volume = 120\n'
            '[[strip.profiles]]\nlabel = "A"\nprofile = "a"\n'
            '[[strip.profiles]]\nlabel = "B"\nprofile = "b"\nmin_volume = 150\n',
            "strip[1].profiles[2]: min_volume (150) is not below max_volume (120)",
        ),
        ('[[strip]]\ntype = "auto"\nmax_volume = 201\n', "strip[1].max_volume"),
    ],
)
def test_a_volume_range_goes_up(text: str, message: str) -> None:
    assert message in errors_of(text)


def test_strips_and_profiles_have_volume_ranges_of_their_own() -> None:
    config = parse_config(
        '[behavior]\nmax_volume = 120\n[[strip]]\ntype = "output"\nmin_volume = 10\n'
        '[[strip.profiles]]\nlabel = "Phones"\nprofile = "a"\n'
        '[[strip.profiles]]\nlabel = "Speaker"\nprofile = "b"\nmin_volume = 50\nmax_volume = 200\n'
        '[[strip]]\ntype = "auto"\n'
    )
    assert config.strips[0].volume_ranges(config.behavior) == [  # type: ignore[union-attr]
        ("", 10, 120),
        ("profiles[1]", 10, 120),
        ("profiles[2]", 50, 200),
    ]
    assert config.strips[1].volume_ranges(config.behavior) == [("", 0, 120)]  # type: ignore[union-attr]


def test_a_strip_has_only_the_encoders_of_its_type() -> None:
    assert parse_config('[[strip]]\ntype = "auto"\nencoder = "pick"\n').strips[0].encoder == "pick"  # type: ignore[union-attr]
    with pytest.raises(
        ConfigError, match=r"strip\[1\]: encoder: pick is not for output strips \(balance, volume, homeassistant\)"
    ):
        parse_config('[[strip]]\ntype = "output"\nencoder = "pick"\n')


def test_the_fader_or_the_encoder_of_an_audio_strip_in_home_assistant() -> None:
    mqtt = '[mqtt]\nhost = "broker"\n'
    output = '[[strip]]\ntype = "output"\n'
    config = parse_config(
        output
        + 'fader = "homeassistant"\n'
        + '[[strip]]\ntype = "auto"\nencoder = "homeassistant"\nid = "desk"\n'
        + mqtt
    )
    assert [strip_id for _, strip_id in config.home_assistant_strips()] == ["strip_1", "desk"]

    with pytest.raises(ConfigError, match=r"strips in Home Assistant need an \[mqtt\] section"):
        parse_config(output + 'encoder = "homeassistant"\n')
    with pytest.raises(ConfigError, match="encoder: with the fader in Home Assistant, the encoder sets the volume"):
        parse_config(output + 'fader = "homeassistant"\nencoder = "balance"\n' + mqtt)
    with pytest.raises(ConfigError, match="the same id: desk"):
        parse_config(
            output
            + 'fader = "homeassistant"\nid = "desk"\n'
            + '[[strip]]\ntype = "homeassistant"\nid = "desk"\n'
            + mqtt
        )


def test_layouts_have_strips_of_their_own() -> None:
    config = parse_config(GAMING)
    assert config.layout_names == ("default", "gaming")
    default, gaming = config.layout_list()
    assert (default.name, default.title, default.strips) == ("default", "Default", config.strips)
    assert (gaming.title, gaming.apps, gaming.processes, gaming.priority) == ("Gaming", ("steam_app_",), ("mumble",), 2)
    assert gaming.has_rules
    assert not default.has_rules
    assert config.layout("gaming") is gaming
    with pytest.raises(KeyError):
        config.layout("nope")
    assert [strip.type for strip in config.all_strips()] == ["output", "apps", *["auto"] * 6]
    strips = config.all_strips("gaming")
    # inherit takes the strip of the default layout at its place: an auto strip after its two strips
    assert [strip.type for strip in strips] == ["output", "voip", "voip", "voip", "auto", "auto", "auto", "auto"]
    assert strips[0] is config.strips[0]
    alice = strips[2]
    assert isinstance(alice, VoipStripConfig)
    assert (alice.person, alice.title) == (("Alice", "alice-phone"), "Alice")
    assert parse_config('[[layout]]\nname = "x"\n').layout("x").title == "x"


def test_the_default_switching() -> None:
    switching = parse_config("").switching
    assert (switching.hold, switching.chord, switching.banner) == (10.0, (1, 8), 1.5)
    assert parse_config("[switching]\nchord = []\n").switching.chord == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[layout]]\nname = "default"\n', "layout: default is the name of the top-level strips"),
        ('[[layout]]\nname = "a"\n[[layout]]\nname = "a"\n', "layouts with the same name: a"),
        ('[[layout]]\nname = "Gaming"\n', r"layout\[1\].name: String should match pattern"),
        ('[[strip]]\ntype = "inherit"\n', r"strip\[1\]: inherit of the default layout is only for"),
        (
            '[voip]\n[[layout]]\nname = "a"\n'
            + '[[layout.strip]]\ntype = "voip"\n' * 8
            + '[[layout.strip]]\ntype = "auto"\n',
            r"layout\[1\].strip\[9\] can never show: 8 strips before them don't collapse",
        ),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "voip"\ncount = 5\n',
            r"layout\[1\].strip\[1\]: count is gone: write N voip strips; voip strips without `person` form a group",
        ),
        (
            '[[strip]]\ntype = "voip"\nmeter_point = "pre_fader"\n',
            r"strip\[1\]: meter_point: the voice chat tells the level of a participant after their volume",
        ),
        ('[behavior]\nmeter_point = "pre"\n', r"behavior.meter_point: Input should be 'pre_fader' or 'post_fader'"),
        (
            '[[strip]]\ntype = "voip"\nperson = "Bob"\n[[strip]]\ntype = "voip"\nperson = ["Carol", "BOB"]\n',
            "voip strips with the same person: bob",
        ),
        (
            '[[strip]]\ntype = "voip"\nperson = "Bob"\n[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\n'
            '[[layout.strip]]\ntype = "inherit"\nstrip = 1\n',
            r"voip strips with the same person \(layout a\): bob",
        ),
        ('[[strip]]\ntype = "voip"\nperson = [" "]\n', r"strip\[1\].person: Value error, an empty name|an empty name"),
        ('[[strip]]\ntype = "voip"\nlabel = "Group"\n', "label: only with person"),
        (
            '[[strip]]\ntype = "output"\n[[layout]]\nname = "a"\n'
            + '[[layout.strip]]\ntype = "auto"\ncollapse = true\n' * 8
            + '[[layout.strip]]\ntype = "inherit"\n',
            r"layout\[1\].strip\[9\]: inherit, but the default layout has only 8 strips",
        ),
        ("[switching]\nchord = [3, 3]\n", "at least two strips, or none"),
        ('[[layout]]\nname = "a"\napps = [" "]\n', "an empty pattern would match every application"),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "output"\nmin_volume = 90\nmax_volume = 50\n',
            r"layout\[1\].strip\[1\]: min_volume \(90\) is not below max_volume \(50\)",
        ),
        (
            '[mqtt]\nhost = "b"\n[[layout]]\nname = "a"\n' + '[[layout.strip]]\ntype = "homeassistant"\nid = "x"\n' * 2,
            r"strips in Home Assistant with the same id \(layout a\): x",
        ),
        ('[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "homeassistant"\n', r"need an \[mqtt\] section"),
        ('[[layout]]\nname = "a"\nlabel = "' + "x" * 57 + '"\n', "at most 56 characters"),
    ],
)
def test_errors_of_layouts(text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(text)


def test_home_assistant_strips_of_a_layout() -> None:
    config = parse_config(
        '[mqtt]\nhost = "b"\n[[strip]]\ntype = "homeassistant"\nid = "desk"\n'
        '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "auto"\n[[layout.strip]]\ntype = "homeassistant"\n'
        '[[layout.strip]]\ntype = "homeassistant"\nid = "desk"\n'
    )
    assert [strip_id for _, strip_id in config.home_assistant_strips()] == ["desk"]
    assert [strip_id for _, strip_id in config.home_assistant_strips("a")] == ["strip_2", "desk"]


def test_voip_strips_get_the_defaults_of_a_missing_voip_section():
    config = parse_config('[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "voip"\n')
    assert config.voip == VoipConfig()
    # without voip strips, no voice chat
    assert parse_config("").voip is None
