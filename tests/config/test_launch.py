"""
`launch` and `launch_when_running` of channels, and the `choices` of a device channel.
"""

import pytest

from tests.support.config import errors_of
from xtouch_daemon.config.audio_strips import AppsStripConfig, ChoiceConfig, DeviceStripConfig
from xtouch_daemon.config.files import parse_config

APPS = '[channel.c]\ntype = "apps"\nmatch = ["mumble"]\nlabel = "VoIP"\n'


def test_launch_is_a_command_as_a_list_or_one_string():
    listed = parse_config(APPS + 'launch = ["mumble", "mumble://me@example.org/Gaming"]\n').slots.channels["c"]
    assert isinstance(listed, AppsStripConfig)
    assert listed.launch == ("mumble", "mumble://me@example.org/Gaming")
    assert not listed.launch_when_running
    one = parse_config(APPS + "launch = \"spotify --uri 'spotify:playlist:x y' ~/$HOME\"\n").slots.channels["c"]
    assert isinstance(one, AppsStripConfig)
    # split like a shell would, but nothing is expanded
    assert one.launch == ("spotify", "--uri", "spotify:playlist:x y", "~/$HOME")


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
    assert message in errors_of(APPS + f"launch = {launch}\n")


@pytest.mark.parametrize("channel", ['type = "output"', 'type = "input"', 'type = "homeassistant"'])
def test_channels_whose_select_is_taken_have_no_launch(channel: str):
    text = f'[mqtt]\nhost = "broker"\n[channel.c]\n{channel}\nlaunch = ["mumble"]\n'
    assert "\n  channel.c: launch: " in errors_of(text)


def test_launch_when_running_needs_launch_and_auto_has_none():
    assert "channel.c: launch_when_running: needs launch" in errors_of(APPS + "launch_when_running = true\n")
    assert "slots.1[0]: launch is no option of a place for auto" in errors_of(
        '[slots]\n1 = [{ show = "auto", launch = ["x"] }]\n'
    )


CHOICES = (
    '[channel.c]\ntype = "output"\n'
    'choices = [{ label = "Phones", device = "alsa_output.*.analog-stereo", card = "alsa_card.*",'
    ' profile = "output:analog-stereo" }, { label = "Buds", device = "bluez_output.*", max_volume = 150 }]\n'
)


def test_a_channel_switches_between_choices() -> None:
    config = parse_config(CHOICES)
    strip = config.slots.channels["c"]
    assert isinstance(strip, DeviceStripConfig)
    assert strip.switches
    assert [choice.title for choice in strip.choices] == ["Phones", "Buds"]
    assert strip.volume_ranges(config.behavior) == [("", 0, 130), ("choices[1]", 0, 130), ("choices[2]", 0, 150)]
    assert ChoiceConfig(device="speaker").title == "speaker"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[channel.c]\ntype = "output"\nchoices = [{ device = "a" }]\n', "channel.c: choices: at least two"),
        (CHOICES + 'device = "a"\n', "channel.c: use either choices or device/profiles"),
        (
            CHOICES
            + '[[channel.c.profiles]]\nlabel = "A"\nprofile = "a"\n'
            + '[[channel.c.profiles]]\nlabel = "B"\nprofile = "b"\n',
            "use either choices or device/profiles",
        ),
        (CHOICES + "select = false\n", "choices: no button switches between them"),
        (
            '[channel.c]\ntype = "output"\nchoices = [{ device = "a", card = "c" }, { device = "b" }]\n',
            "channel.c: choices.0: card and profile go together",
        ),
        ('[channel.c]\ntype = "output"\nchoices = [{ device = " " }, { device = "b" }]\n', "an empty device name"),
        (
            '[channel.c]\ntype = "output"\nchoices = [{ device = "a", min_volume = 140 }, { device = "b" }]\n',
            "channel.c.choices[1]: min_volume (140) is not below max_volume (130)",
        ),
    ],
)
def test_choices_are_checked(text: str, message: str) -> None:
    assert message in errors_of(text)
