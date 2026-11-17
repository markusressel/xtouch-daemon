"""
`launch` and `launch_when_running` on strips.
"""

import re

import pytest

from tests.support.config import legacy, legacy_errors_of
from xtouch_daemon.config.audio_strips import AppsStripConfig, AutoStripConfig, ChoiceConfig, DeviceStripConfig
from xtouch_daemon.config.layout_strips import VoipStripConfig


def test_launch_is_a_command_as_a_list_or_one_string():
    config = legacy(
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
    assert message in legacy_errors_of(f'[[strip]]\ntype = "auto"\nlaunch = {launch}\n')


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
    assert "\n  strip[1].launch: " in legacy_errors_of(text)


def test_launch_when_running_needs_launch_and_is_not_for_voip_strips():
    auto = '[[strip]]\ntype = "auto"\nlaunch_when_running = true\n'
    assert "launch_when_running: needs launch" in legacy_errors_of(auto)
    text = '[voip]\n[[strip]]\ntype = "voip"\nlaunch = ["mumble"]\nlaunch_when_running = true\n'
    assert "strip[1].launch_when_running: " in legacy_errors_of(text)


CHOICES = (
    '[[strip]]\ntype = "output"\n'
    'choices = [{ label = "Phones", device = "alsa_output.*.analog-stereo", card = "alsa_card.*",'
    ' profile = "output:analog-stereo" }, { label = "Buds", device = "bluez_output.*", max_volume = 150 }]\n'
)


def test_a_strip_switches_between_choices() -> None:
    config = legacy(CHOICES)
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
    assert re.search(message, legacy_errors_of(text))


def test_strips_with_collapse_may_be_more_than_the_device_has() -> None:
    config = legacy('[[strip]]\ntype = "output"\ndevice = "buds"\ncollapse = true\n' + '[[strip]]\ntype = "auto"\n' * 8)
    assert len(config.all_strips()) == 9
    assert config.unreachable() == []
    assert config.behavior.collapse_hold == 3.0
    # fewer than 8: the rest are auto
    assert [strip.type for strip in legacy('[[strip]]\ntype = "empty"\n').all_strips()] == ["empty"] + ["auto"] * 7


def test_a_strip_that_could_never_show_is_an_error() -> None:
    message = legacy_errors_of('[[strip]]\ntype = "auto"\n' * 8 + '[[strip]]\ntype = "auto"\ncollapse = true\n' * 2)
    assert "strip[9], strip[10] can never show: 8 strips before them don't collapse" in message


@pytest.mark.parametrize(
    ("strip", "message"),
    [
        ('type = "homeassistant"', "a homeassistant strip stays, automations rely on its entities"),
        ('type = "empty"', "an empty strip is there to keep its place"),
    ],
)
def test_some_strips_never_collapse(strip: str, message: str) -> None:
    assert message in legacy_errors_of(f'[mqtt]\nhost = "b"\n[[strip]]\n{strip}\ncollapse = true\n')
