"""
The configuration file: its sections, the options of channels and their checks.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.support.config import MQTT, errors_of
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
from xtouch_daemon.config.model import Config
from xtouch_daemon.config.sections import DeviceConfig
from xtouch_daemon.config.strips import STRIP_MODELS, STRIP_TYPES, EmptyStripConfig, HomeAssistantStripConfig
from xtouch_daemon.config.values import color_of
from xtouch_daemon.config.voip_strips import VoipStripConfig
from xtouch_daemon.hardware.protocol import Color

FULL = """
[device]
name = "X-Touch-Ext"

[behavior]
max_volume = 120
encoder_step = 2
reset_volume = 80
meters = false

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[channel.out]
type = "output"
device = "alsa_output.analog"
label = "Speaker"
color = "cyan"
select = false

[channel.voip]
type = "apps"
match = ["discord", "mumble"]
label = "VoIP"
color = "off"
meter = false

[slots]
1 = "out"
2 = "voip"
"""


def channel(options: str, name: str = "c") -> str:
    """A file with one channel of these options."""
    return f"[channel.{name}]\n{options}"


def test_reads_every_option():
    config = parse_config(FULL)

    assert config.behavior.max_volume == 120
    assert config.behavior.encoder_step == 2
    assert config.behavior.reset_volume == 80
    assert not config.behavior.meters
    assert config.aliases == {"WEBRTC VoiceEngine": "Discord"}
    assert config.slots.channels["out"] == DeviceStripConfig(
        type="output", device=("alsa_output.analog",), label="Speaker", color="cyan", select=False
    )
    assert config.slots.channels["voip"] == AppsStripConfig(
        type="apps", match=("discord", "mumble"), label="VoIP", color="off", meter=False
    )


def test_an_empty_file_is_the_defaults():
    config = parse_config("")
    assert config.device.name == "X-Touch-Ext"
    assert config.behavior.max_volume == 130


def test_colors_have_their_lcd_color():
    assert color_of("off") == Color.BLACK
    assert color_of("cyan") == Color.CYAN
    assert color_of("white") == Color.WHITE


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
        # a typo in an option name
        ("[behavior]\nmax_volum = 120", "behavior.max_volum"),
        ('[aliases]\nBrave = "Browser!!"', "aliases.Brave"),
        # what is gone with strips and layouts
        ('[[strip]]\ntype = "auto"\n', "strip"),
        ("[behavior]\nauto_hold = 2", "behavior.auto_hold"),
        (channel('type = "output"\nlabel = "Lautsprecher"'), "channel.c: label"),
        (channel('type = "output"\nlabel = "Grüße"'), "channel.c: label"),
        (channel('type = "apps"\nmatch = ["x"]\nlabel = "A"\ncolor = "pink"'), "channel.c: color"),
        (channel('type = "apps"\nmatch = ["discord"]'), "channel.c: label"),
        (channel('type = "fader"'), "channel.c.type"),
        ('[slots]\n1 = [{ show = "auto", color = "pink" }]\n', "slots.1[0]: color"),
    ],
)
def test_errors_name_the_option(text: str, location: str):
    message = errors_of(text)
    assert message.startswith("config.toml has errors:\n")
    assert f"\n  {location}: " in message


def test_a_blank_pattern_would_match_every_application():
    message = errors_of(channel('type = "apps"\nmatch = ["discord", " "]\nlabel = "VoIP"'))
    assert "channel.c: match: an empty pattern would match every application" in message


def test_a_list_at_the_top_level_names_its_position():
    # pydantic never reports one for the top-level table of a TOML file
    assert Problem((0, "label"), "", "").location == "0.label"
    assert Problem(("device", "touchless_faders", 1), "", "").location == "device.touchless_faders[2]"


def test_problems_name_the_place_in_the_toml_data():
    with pytest.raises(ValidationError) as error:
        Config.model_validate({"aliases": {"output": "too long"}, "device": {"touchless_faders": [1, 9]}})

    assert [(problem.path, problem.kind) for problem in problems_of(error.value)] == [
        (("device", "touchless_faders", 1), "less_than_equal"),
        (("aliases", "output"), "string_too_long"),
    ]
    assert str(problems_of(error.value)[0]).startswith("device.touchless_faders[2]: ")


def test_the_strip_types_are_the_ones_of_the_models():
    assert (
        DeviceStripConfig,
        AppsStripConfig,
        AutoStripConfig,
        HomeAssistantStripConfig,
        EmptyStripConfig,
        VoipStripConfig,
    ) == STRIP_MODELS
    assert STRIP_TYPES == ("output", "input", "apps", "auto", "homeassistant", "empty", "voip")


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
    text = '[channel.out]\ntype = "output"\n[slots]\n1 = "out"\n'
    path.write_text(text)
    assert load_config(path) == parse_config(text)


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


def test_the_mqtt_section_has_defaults():
    config = parse_config(MQTT)

    assert config.mqtt is not None
    assert config.mqtt.port == 1883
    assert config.mqtt.discovery_prefix == "homeassistant"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (channel('type = "homeassistant"'), "channel.c: Home Assistant needs an [mqtt] section"),
        (channel('type = "homeassistant"\nid = "Desk Lights"\n') + MQTT, "channel.c: id: String should match"),
        (channel('type = "homeassistant"\nmeter = false\n') + MQTT, "channel.c: meter: Extra inputs"),
        (MQTT + 'password = "a"\npassword_env = "B"\n', "set only one of password, password_env"),
        (MQTT + "port = 0\n", "mqtt.port"),
    ],
)
def test_errors_of_home_assistant(text: str, message: str):
    assert message in errors_of(text)


def test_a_device_channel_takes_one_device_or_several() -> None:
    config = parse_config(channel('type = "output"\ndevice = ["bluez_output.*", "Speaker"]\n'))
    assert config.slots.channels["c"] == DeviceStripConfig(type="output", device=("bluez_output.*", "Speaker"))
    assert DeviceStripConfig.model_validate({"type": "output", "device": "speaker"}).device == ("speaker",)

    assert "channel.c: device: an empty device name" in errors_of(
        channel('type = "output"\ndevice = ["speaker", " "]\n')
    )


def test_a_device_channel_switches_between_two_or_more_profiles_with_rec() -> None:
    analog = '[[channel.c.profiles]]\nlabel = "Analog"\nprofile = "output:analog-stereo"\n'
    profiles = analog + '[[channel.c.profiles]]\nlabel = "Digital"\nprofile = "Digital Stereo (IEC958) Output"\n'
    strip = channel('type = "output"\ndevice = "alsa_output.*"\n')
    config = parse_config(strip + profiles)
    assert [p.label for p in config.slots.channels["c"].profiles] == ["Analog", "Digital"]  # type: ignore[union-attr]

    assert "channel.c: profiles: at least two to switch between" in errors_of(strip + analog)
    # its LED shows the profile
    assert "rec: with profiles its LED shows the profile" in errors_of(
        strip.replace("\ndevice", '\nrec = "playing"\ndevice') + profiles
    )
    assert "channel.c: profiles.0.label" in errors_of(strip + profiles.replace('"Analog"', '"Analog Stereo"'))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[slots]\n1 = [{ show = "auto", min_volume = 130 }]\n',
            "slots.1[0]: min_volume (130) is not below max_volume (130)",
        ),
        (
            channel('type = "apps"\nmatch = ["a"]\nlabel = "A"\nmin_volume = 50\nmax_volume = 40\n'),
            "channel.c: min_volume (50) is not below max_volume (40)",
        ),
        (
            channel('type = "output"\nmax_volume = 120\n')
            + '[[channel.c.profiles]]\nlabel = "A"\nprofile = "a"\n'
            + '[[channel.c.profiles]]\nlabel = "B"\nprofile = "b"\nmin_volume = 150\n',
            "min_volume (150) is not below max_volume (120)",
        ),
        ('[slots]\n1 = [{ show = "auto", max_volume = 201 }]\n', "slots.1[0]: max_volume"),
    ],
)
def test_a_volume_range_goes_up(text: str, message: str) -> None:
    assert message in errors_of(text)


def test_channels_and_profiles_have_volume_ranges_of_their_own() -> None:
    config = parse_config(
        "[behavior]\nmax_volume = 120\n"
        + channel('type = "output"\nmin_volume = 10\n')
        + '[[channel.c.profiles]]\nlabel = "Phones"\nprofile = "a"\n'
        '[[channel.c.profiles]]\nlabel = "Speaker"\nprofile = "b"\nmin_volume = 50\nmax_volume = 200\n'
    )
    assert config.slots.channels["c"].volume_ranges(config.behavior) == [  # type: ignore[union-attr]
        ("", 10, 120),
        ("profiles[1]", 10, 120),
        ("profiles[2]", 50, 200),
    ]


def test_a_channel_has_only_the_encoders_of_its_type() -> None:
    assert "channel.c: encoder: pick is not for output strips (balance, volume, homeassistant)" in errors_of(
        channel('type = "output"\nencoder = "pick"\n')
    )


def test_the_fader_or_the_encoder_of_an_audio_channel_in_home_assistant() -> None:
    output = channel('type = "output"\n')
    parse_config(output + 'fader = "homeassistant"\n' + MQTT)

    assert "channel.c: Home Assistant needs an [mqtt] section" in errors_of(output + 'encoder = "homeassistant"\n')
    assert "encoder: with the fader in Home Assistant, the encoder sets the volume" in errors_of(
        output + 'fader = "homeassistant"\nencoder = "balance"\n' + MQTT
    )


def test_the_default_switching() -> None:
    switching = parse_config("").switching
    assert (switching.chord, switching.banner) == ((1, 8), 1.5)
    assert parse_config("[switching]\nchord = []\n").switching.chord == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[behavior]\nmeter_point = "pre"\n', "behavior.meter_point: Input should be 'pre_fader' or 'post_fader'"),
        (
            '[voip]\n[channel.a]\ntype = "person"\nperson = "Bob"\n'
            '[channel.b]\ntype = "person"\nperson = ["Carol", "BOB"]\n',
            "channel.b: BOB is also a person of channel a",
        ),
        ("[voip]\n" + channel('type = "person"\nperson = [" "]\n'), "channel.c: person: an empty name"),
        ("[switching]\nchord = [3, 3]\n", "at least two strips, or none"),
    ],
)
def test_errors_of_people_and_switching(text: str, message: str) -> None:
    assert message in errors_of(text)
