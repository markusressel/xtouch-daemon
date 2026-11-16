import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from xtouch_daemon.config import presets
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, ChoiceConfig, DeviceStripConfig
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
from xtouch_daemon.config.sections import BehaviorConfig, DeviceConfig, VoipConfig
from xtouch_daemon.config.strips import STRIP_MODELS, STRIP_TYPES, EmptyStripConfig, HomeAssistantStripConfig
from xtouch_daemon.config.values import color_of
from xtouch_daemon.hardware.protocol import Color

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


def errors_of(text: str) -> str:
    with pytest.raises(ConfigError) as error:
        parse_config(text, "config.toml")
    return str(error.value)


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


HOME_ASSISTANT = '[[strip]]\ntype = "homeassistant"\n'
MQTT = '[mqtt]\nhost = "broker"\n'


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


GAMING = """
[[strip]]
type = "output"
label = "Speaker"

[[strip]]
type = "apps"
match = ["firefox"]
label = "Web"

[voip]
provider = "demo"

[[layout]]
name = "gaming"
label = "Gaming"
apps = ["steam_app_"]
processes = ["mumble"]
priority = 2

[[layout.strip]]
type = "inherit"

[[layout.strip]]
type = "voip"
talking_color = "yellow"

[[layout.strip]]
type = "voip"
person = ["Alice", "alice-phone"]

[[layout.strip]]
type = "voip"

[[layout.strip]]
type = "inherit"
"""


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


# -- launch -------------------------------------------------------------------------------------------------------


def test_launch_is_a_command_as_a_list_or_one_string():
    config = parse_config(
        '[voip]\n[[strip]]\ntype = "apps"\nmatch = ["mumble"]\nlabel = "VoIP"\n'
        'launch = ["mumble", "mumble://me@example.org/Gaming"]\n'
        '[[strip]]\ntype = "auto"\nlaunch = "spotify --uri \'spotify:playlist:x y\' ~/$HOME"\n'
        '[[strip]]\ntype = "voip"\nlaunch = ["mumble"]\n'
    )
    apps, auto, voip = config.strips[:3]
    assert isinstance(apps, AppsStripConfig)
    assert isinstance(auto, AutoStripConfig)
    assert isinstance(voip, VoipStripConfig)
    assert apps.launch == ("mumble", "mumble://me@example.org/Gaming")
    assert not apps.launch_when_running
    # split like a shell would, but nothing is expanded
    assert auto.launch == ("spotify", "--uri", "spotify:playlist:x y", "~/$HOME")
    assert voip.launch == ("mumble",)


@pytest.mark.parametrize(
    ("launch", "message"),
    [
        ("[]", "an empty command"),
        ('""', "an empty command"),
        ('["mumble", " "]', "an empty part of the command"),
        ('"mumble \'x"', "can't split the command: No closing quotation"),
        ("42", "launch"),
    ],
)
def test_a_launch_that_is_no_command_is_an_error(launch: str, message: str):
    assert message in errors_of(f'[[strip]]\ntype = "auto"\nlaunch = {launch}\n')


@pytest.mark.parametrize(
    "strip",
    [
        'type = "output"',
        'type = "input"',
        'type = "homeassistant"',
        'type = "empty"',
    ],
)
def test_strips_whose_select_is_taken_have_no_launch(strip: str):
    text = f'[mqtt]\nhost = "broker"\n[[strip]]\n{strip}\nlaunch = ["mumble"]\n'
    assert "\n  strip[1].launch: " in errors_of(text)


def test_launch_when_running_needs_launch_and_is_not_for_voip_strips():
    assert "launch_when_running: needs launch" in errors_of('[[strip]]\ntype = "auto"\nlaunch_when_running = true\n')
    text = '[voip]\n[[strip]]\ntype = "voip"\nlaunch = ["mumble"]\nlaunch_when_running = true\n'
    assert "strip[1].launch_when_running: " in errors_of(text)


CHOICES = (
    '[[strip]]\ntype = "output"\n'
    'choices = [{ label = "Phones", device = "alsa_output.*.analog-stereo", card = "alsa_card.*",'
    ' profile = "output:analog-stereo" }, { label = "Buds", device = "bluez_output.*", max_volume = 150 }]\n'
)


def test_a_strip_switches_between_choices() -> None:
    config = parse_config(CHOICES)
    strip = config.strips[0]
    assert isinstance(strip, DeviceStripConfig)
    assert strip.switches
    assert [choice.title for choice in strip.choices] == ["Phones", "Buds"]
    assert strip.volume_ranges(config.behavior) == [("", 0, 130), ("choices[1]", 0, 130), ("choices[2]", 0, 150)]
    assert ChoiceConfig(device="speaker").title == "speaker"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[strip]]\ntype = "output"\nchoices = [{ device = "a" }]\n', r"strip\[1\].choices: at least two"),
        (CHOICES + 'device = "a"\n', r"strip\[1\]: use either choices or device/profiles"),
        (
            CHOICES
            + '[[strip.profiles]]\nlabel = "A"\nprofile = "a"\n[[strip.profiles]]\nlabel = "B"\nprofile = "b"\n',
            "use either choices or device/profiles",
        ),
        (CHOICES + "select = false\n", "select: with choices, Select is how the strip switches between them"),
        (
            '[[strip]]\ntype = "output"\nchoices = [{ device = "a", card = "c" }, { device = "b" }]\n',
            r"strip\[1\].choices\[1\]: card and profile go together",
        ),
        ('[[strip]]\ntype = "output"\nchoices = [{ device = " " }, { device = "b" }]\n', "an empty device name"),
        (
            '[[strip]]\ntype = "output"\nchoices = [{ device = "a", min_volume = 140 }, { device = "b" }]\n',
            r"strip\[1\].choices\[1\]: min_volume \(140\) is not below max_volume \(130\)",
        ),
        (
            '[mqtt]\nhost = "b"\n' + (CHOICES + 'id = "out"\n') * 2,
            "strips in Home Assistant with the same id: out",
        ),
    ],
)
def test_choices_are_checked(text: str, message: str) -> None:
    assert re.search(message, errors_of(text))


def test_strips_with_collapse_may_be_more_than_the_device_has() -> None:
    config = parse_config(
        '[[strip]]\ntype = "output"\ndevice = "buds"\ncollapse = true\n' + '[[strip]]\ntype = "auto"\n' * 8
    )
    assert len(config.all_strips()) == 9
    assert config.unreachable() == []
    assert config.behavior.collapse_hold == 3.0
    # fewer than 8: the rest are auto
    assert [strip.type for strip in parse_config('[[strip]]\ntype = "empty"\n').all_strips()] == ["empty"] + [
        "auto"
    ] * 7


def test_a_strip_that_could_never_show_is_an_error() -> None:
    message = errors_of('[[strip]]\ntype = "auto"\n' * 8 + '[[strip]]\ntype = "auto"\ncollapse = true\n' * 2)
    assert "strip[9], strip[10] can never show: 8 strips before them don't collapse" in message


@pytest.mark.parametrize(
    ("strip", "message"),
    [
        ('type = "homeassistant"', "a homeassistant strip stays, automations rely on its entities"),
        ('type = "empty"', "an empty strip is there to keep its place"),
    ],
)
def test_some_strips_never_collapse(strip: str, message: str) -> None:
    assert message in errors_of(f'[mqtt]\nhost = "b"\n[[strip]]\n{strip}\ncollapse = true\n')


# -- inherit from any layout and strip ----------------------------------------------------------------------------

INHERIT = """
[mqtt]
host = "broker"

[voip]

[[strip]]
type = "output"
label = "Out"
collapse = true

[[strip]]
type = "apps"
match = ["spotify"]
label = "Music"
id = "music"
launch = ["spotify"]

[[strip]]
type = "homeassistant"

[[layout]]
name = "voice"

[[layout.strip]]
type = "voip"

[[layout.strip]]
type = "voip"
person = "Ann"

[[layout.strip]]
type = "inherit"
strip = "music"

[[layout]]
name = "games"

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 1

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 2

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 3

[[layout.strip]]
type = "inherit"
strip = 3

[[layout.strip]]
type = "inherit"
layout = "voice"
"""


def test_an_inherit_strip_takes_any_strip_of_any_layout() -> None:
    config = parse_config(INHERIT)
    voice, games = config.all_strips("voice"), config.all_strips("games")
    # the same strips, the same objects
    assert (voice[0], voice[1]) == (games[0], games[1])
    assert voice[0] is games[0]
    assert voice[1] is games[1]
    # with all their options: launch, collapse
    music = config.strips[1]
    assert voice[2] is games[2] is music
    assert isinstance(music, AppsStripConfig)
    assert music.launch == ("spotify",)
    assert config.inherited("games")[:3] == (
        "layout voice, strip 1",
        "layout voice, strip 2",
        "the default layout, strip 2",
    )
    # the homeassistant strip keeps the entities of its place in the default layout
    home_assistant = games[3]
    assert isinstance(home_assistant, HomeAssistantStripConfig)
    assert home_assistant.id == "strip_3"
    assert config.home_assistant_strips("games") == [(home_assistant, "strip_3")]
    # without strip: the same place, which voice has no strip for
    assert games[4].type == "auto"


def test_an_inherit_strip_in_the_default_layout_names_its_strip() -> None:
    config = parse_config(
        '[[strip]]\ntype = "inherit"\nlayout = "a"\n[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "output"\n'
    )
    assert config.all_strips()[0] is config.layout("a").strips[0]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nlayout = "b"\n',
            r"layout\[1\].strip\[1\]: inherit from the layout b, which is not there",
        ),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nstrip = 2\n',
            "inherit strip 2, but the default layout has 0 strips",
        ),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nstrip = "x"\n',
            "inherit strip x, but the default layout has no strip with that id",
        ),
        (
            '[[strip]]\ntype = "auto"\nid = "x"\n[[strip]]\ntype = "auto"\nid = "x"\n'
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nstrip = "x"\n',
            "inherit strip x, but the default layout has 2 strips with that id",
        ),
        (
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\nlayout = "b"\nstrip = 1\n'
            '[[layout]]\nname = "b"\n[[layout.strip]]\ntype = "inherit"\nlayout = "a"\nstrip = 1\n',
            r"inherit strips that refer to each other: layout\[1\].strip\[1\] -> layout\[2\].strip\[1\] -> "
            r"layout\[1\].strip\[1\]",
        ),
        (
            '[[layout]]\nname = "a"\n'
            + "".join(f'[[layout.strip]]\ntype = "inherit"\nlayout = "a"\nstrip = {n + 1}\n' for n in range(1, 10))
            + '[[layout.strip]]\ntype = "auto"\ncollapse = true\n',
            r"layout\[1\].strip\[1\]: more than 8 inherit strips refer to one another",
        ),
        (
            '[mqtt]\nhost = "b"\n[[strip]]\ntype = "homeassistant"\n'
            '[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "homeassistant"\n'
            '[[layout.strip]]\ntype = "inherit"\nlayout = "default"\nstrip = 1\n',
            "strips in Home Assistant with the same id \\(layout a\\): strip_1",
        ),
    ],
)
def test_errors_of_inherit_strips(text: str, message: str) -> None:
    assert re.search(message, errors_of(text))


# -- presets ----------------------------------------------------------------------------------------------------------

PRESETS_CONFIG = """\
[behavior]
ignore = ["@music", "notification"]

[[strip]]
type = "apps"
match = ["@browsers", "netsurf"]
label = "Browser"

[[layout]]
name = "gaming"
apps = ["@games"]
processes = ["@steam-games", "lutris"]
"""


def test_presets_stand_for_their_names_and_keep_how_they_are_written():
    config = parse_config(PRESETS_CONFIG)
    (strip, *_) = config.all_strips()
    assert isinstance(strip, AppsStripConfig)
    assert strip.match[0] == "firefox"
    assert strip.match[-1] == "netsurf"
    assert strip.written("match") == ("@browsers", "netsurf")
    assert "spotify" in config.behavior.ignore
    assert config.behavior.written("ignore") == ("@music", "notification")
    (gaming,) = config.layouts
    assert gaming.apps == ("steam_app_", ".exe", "wine-preloader", "wine64-preloader")
    assert gaming.processes == ("reaper", "lutris")
    assert gaming.written("processes") == ("@steam-games", "lutris")


def test_lists_without_presets_are_written_as_they_are():
    config = parse_config('[[strip]]\ntype = "apps"\nmatch = ["brave"]\nlabel = "B"\n')
    strip = config.strips[0]
    assert isinstance(strip, AppsStripConfig)
    assert strip.written("match") == ("brave",)
    assert config.behavior.written("ignore") == ("speech-dispatcher",)
    # what the models compare: the same file is the same configuration
    assert parse_config(PRESETS_CONFIG) == parse_config(PRESETS_CONFIG)


def test_the_processes_of_an_apps_strip_are_those_of_its_presets():
    strip = AppsStripConfig(type="apps", match=("@steam-games", "mumble"), label="Games")
    assert strip.process_names == ("reaper", "mumble")
    # an inherited strip is the same strip
    config = parse_config(
        '[[strip]]\ntype = "apps"\nmatch = ["@voip"]\nlabel = "VoIP"\n'
        '[[layout]]\nname = "x"\n[[layout.strip]]\ntype = "empty"\n[[layout.strip]]\ntype = "inherit"\nstrip = 1\n'
    )
    inherited = config.all_strips("x")[1]
    assert isinstance(inherited, AppsStripConfig)
    assert inherited.written("match") == ("@voip",)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[strip]]\ntype = "apps"\nmatch = ["@browser"]\nlabel = "B"',
            "strip[1].match: @browser is no preset; the presets are @browsers, @voip, @steam-games, @games, @music, "
            "@video",
        ),
        ('[[layout]]\nname = "x"\nprocesses = ["@nope"]', "layout[1].processes: @nope is no preset; "),
        ('[behavior]\nignore = ["@"]', "behavior.ignore: @ is no preset; "),
    ],
)
def test_an_unknown_preset_is_an_error_of_its_option(text: str, message: str):
    assert f"\n  {message}" in errors_of(text)


def test_a_preset_in_a_list_it_is_not_for_says_where_it_fits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(presets, "PRESETS", {"toys": presets.Preset("toys", "Toys", streams=("rattle",))})
    message = errors_of('[[layout]]\nname = "x"\nprocesses = ["@toys"]\napps = ["@toys"]')
    assert (
        "layout[1].processes: @toys is not for `processes` of layouts; use it in `match` of apps strips, `apps` of "
        "layouts and `behavior.ignore`" in message
    )
    assert "layout[1].apps" not in message


def test_a_strip_given_as_a_model_keeps_its_presets():
    strip = AppsStripConfig(type="apps", match=("@voip",), label="VoIP")
    config = Config.model_validate({"strip": [strip]})
    (again,) = config.strips
    assert isinstance(again, AppsStripConfig)
    assert again.written("match") == ("@voip",)
    assert AppsStripConfig.model_validate(strip).written("match") == ("@voip",)


METER_POINTS = """
[behavior]
meter_point = "post_fader"

[[strip]]
type = "output"

[[strip]]
type = "input"
meter_point = "pre_fader"

[[layout]]
name = "gaming"
meter_point = "pre_fader"

[[layout.strip]]
type = "inherit"
strip = 2

[[layout.strip]]
type = "inherit"
strip = 1

[[layout.strip]]
type = "apps"
label = "Game"
match = [".exe"]
meter_point = "post_fader"

[[layout]]
name = "plain"
"""


def test_the_meter_point_of_a_strip_wins_over_the_layout_which_wins_over_the_behavior():
    config = parse_config(METER_POINTS)
    assert BehaviorConfig().meter_point == "pre_fader"

    def points(layout: str) -> list[str]:
        return [config.meter_point(strip, layout) for strip in config.all_strips(layout)][:3]

    # the default layout has no option of its own: [behavior] is its
    assert points("default") == ["post_fader", "pre_fader", "post_fader"]
    # an inherited strip brings its own along, else it takes the one of the layout it is in
    assert points("gaming") == ["pre_fader", "pre_fader", "post_fader"]
    assert points("plain") == ["post_fader"] * 3
    # the auto strips that fill a layout up too
    assert config.meter_point(config.all_strips("gaming")[7], "gaming") == "pre_fader"
