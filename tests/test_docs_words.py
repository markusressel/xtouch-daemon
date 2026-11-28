"""
The pages of the documentation use one word for one thing (AGENTS.md, "Writing docs"). "Device" meant two: the
control surface and a sound device. So a page never says a bare "device": the hardware is the control surface (the
X-Touch Extender, for a fact of the model), a sound device is an output, an input or a sound device. Nor "X-Touch"
alone: that is the bigger desk that the Extender extends. The names of the configuration (`devices`, `device`, in
code) and of the GUI (the window "Device", the virtual device) stay.
docs/development is for developers and is not checked.
"""

import re
from pathlib import Path

import pytest

from tests.test_docs_links import DOCS, pages, prose

GUI = DOCS.parent / "src" / "xtouch_daemon" / "gui"
GUI_LABELS = (
    "On the device",
    "Try without a device",
    "Test the device",
    "device not connected",
    "Sending to the device",
    "Not on the device yet",
)
"""Texts of the GUI that say "device" for the control surface: the docs quote them as the GUI shows them."""

QUALIFIED = re.compile(
    r"\b(?:sound|audio|virtual|MIDI|USB|Bluetooth|ALSA|PipeWire|PulseAudio|input|output|block)\s+[Dd]evices?\b"
    r'|window\s+"?Device"?|"Device"|\*\*Device\*\*|→ Device|"the device"|Home Assistant device|Devices & services'
    "|" + "|".join(re.escape(label).replace(r"\ ", r"\s+") for label in GUI_LABELS)
)
"""The kinds of device a page may name: a sound device, the virtual device, the window "Device", and the like."""
DEVICE = re.compile(r"\b[Dd]evices?\b")


def bare_devices(text: str) -> list[str]:
    """The lines of `text` (its prose, without code) that say a bare "device"."""
    text = QUALIFIED.sub("", re.sub(r"`[^`\n]*`", "", prose(text)))
    return [line.strip() for line in text.splitlines() if DEVICE.search(line)]


@pytest.mark.parametrize("page", pages(), ids=lambda page: page.relative_to(DOCS).as_posix())
def test_a_page_says_which_device_it_means(page: Path):
    bare = bare_devices(page.read_text())
    where = page.relative_to(DOCS)
    assert not bare, f"{where} says a bare device (the X-Touch, or an output or input?):\n" + "\n".join(bare)


def test_the_labels_it_quotes_are_in_the_gui():
    sources = "\n".join(path.read_text() for path in GUI.rglob("*.py"))
    assert [label for label in GUI_LABELS if label not in sources] == []


def test_a_sound_device_and_the_names_of_the_gui_are_fine():
    assert not bare_devices('A sound device, the virtual device and the window "Device". The pool `devices`.')


def test_a_bare_device_is_found():
    assert bare_devices("The device has 8 strips.") == ["The device has 8 strips."]


def test_a_label_of_the_gui_may_break_across_lines():
    assert not bare_devices('Click "Try without a\ndevice" above the drawing.')


def test_code_is_not_prose():
    assert not bare_devices("```toml\ndevice = 'x'\n```\nThe option `device`.")


BARE_XTOUCH = re.compile(r"X-Touch(?! Extender)(?!-Ext)")
"""The X-Touch alone: the bigger desk. `X-Touch-Ext` is the name of the sound card of the Extender."""
THE_BIGGER_ONE = re.compile(r"the bigger X-Touch")
"""Where a page says what the X-Touch is."""


def bare_xtouches(text: str) -> list[str]:
    """The lines of `text` (its prose and headings, without code) that say "X-Touch" for the X-Touch Extender."""
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    text = THE_BIGGER_ONE.sub("", re.sub(r"`[^`\n]*`", "", text))
    return [line.strip() for line in text.splitlines() if BARE_XTOUCH.search(line)]


@pytest.mark.parametrize("page", pages(), ids=lambda page: page.relative_to(DOCS).as_posix())
def test_a_page_says_control_surface(page: Path):
    bare = bare_xtouches(page.read_text())
    where = page.relative_to(DOCS)
    assert not bare, f"{where} says X-Touch (the bigger desk): the control surface, or the X-Touch Extender?\n" + (
        "\n".join(bare)
    )


def test_the_extender_and_its_card_are_fine():
    assert not bare_xtouches("The X-Touch Extender, the card `X-Touch-Ext`, the bigger X-Touch.")
    assert bare_xtouches("The X-Touch has 8 strips.") == ["The X-Touch has 8 strips."]
