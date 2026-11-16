"""
Strips with choices, strips that collapse, and voip strips in the window.
"""

from pathlib import Path

from PyQt6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot

from tests.support.gui import FakeLiveDaemon, MakeWindow, click, row, strip_state, type_into
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.fields.tables import Tables
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import Snapshot, VoipState, fingerprint


def test_choices_or_a_device_with_profiles(qtbot: QtBot, window: MainWindow):
    choices, device, profiles = row(window, "choices"), row(window, "device"), row(window, "profiles")
    # the strip has a device: choices are no option then
    assert [choices.isHidden(), device.isHidden(), profiles.isHidden()] == [True, False, False]
    window.editor.unset(("strip", 0, "device"))
    assert [choices.isHidden(), device.isHidden()] == [False, False]

    tables: Tables = choices.tables
    click(qtbot, tables.add_button)
    type_into(qtbot, tables.lines[0][0], "Phones")
    assert [choices.isHidden(), device.isHidden(), profiles.isHidden()] == [False, True, True]

    def menu_of(column: int) -> list[str]:
        menu_button = tables.lines[0][column].parentWidget().findChildren(QToolButton)[column - 1]  # type: ignore[union-attr]
        menu = menu_button.menu()
        assert menu is not None
        menu.aboutToShow.emit()
        return [action.text() for action in menu.actions()]

    # the devices, the cards and the profiles of the card of the line
    assert menu_of(1)[0].startswith("speaker")
    assert menu_of(2) == ["onboard    speaker"]
    assert menu_of(3) == ["The sound server has none"]
    type_into(qtbot, tables.lines[0][2], "onboard")
    assert menu_of(3)[0] == "output:analog-stereo    Analog Stereo Output (active)"
    assert window.document.get(("strip", 0, "choices")) == [{"label": "Phones", "card": "onboard"}]


NINE = '[[strip]]\ntype = "output"\ncollapse = true\n' + '[[strip]]\ntype = "apps"\nmatch = ["a"]\n' * 8


def test_the_strip_list_reaches_the_strips_beyond_the_device(qtbot: QtBot, make_window: MakeWindow, path: Path):
    window = make_window()
    # 2 strips: no list
    assert window.strip_list.isHidden()
    path.write_text(NINE)
    window = make_window()
    strip_list = window.strip_list
    assert not strip_list.isHidden()
    assert [button.text() for button in strip_list.buttons][7:] == ["8 apps · on 8", "9 apps · waits"]
    assert "waits for a place" in strip_list.buttons[8].toolTip()

    click(qtbot, strip_list.buttons[8])
    assert window.selected == 8
    assert window.tabs.tabText(0).startswith("Strip 9")
    assert strip_list.buttons[8].isChecked()

    # 8 strips without collapse after the first: a tenth could never show
    assert not strip_list.add_button.isEnabled()
    assert "could never show" in strip_list.add_button.toolTip()
    window.editor.unset(("strip", 1, "match"))
    window.document.strips[1].values["collapse"] = True
    window.editor.edited()
    assert strip_list.add_button.isEnabled()
    click(qtbot, strip_list.add_button)
    assert (len(window.document.strips), window.selected) == (10, 9)
    assert len(strip_list.buttons) == 10
    assert window.status.text() == "Added strip 10, an auto strip."

    # fewer again: the buttons go
    window.editor.remove_strip(9)
    assert len(strip_list.buttons) == 9
    assert window.selected == 8
    assert window.strip_page.title.text() == "Strip 9"


def test_an_inherit_strip_picks_its_layout_and_strip(qtbot: QtBot, layouts: MainWindow):
    window = layouts
    window.layout_bar.tabs.setCurrentIndex(1)
    window.select(0)
    layout, strip = row(window, "layout"), row(window, "strip")
    assert layout.line.placeholderText() == "default"

    def menu_of(option_row: OptionRow) -> list[str]:
        menu_button = next(button for button in option_row.findChildren(QToolButton) if button.menu())
        menu = menu_button.menu()
        assert menu is not None
        menu.aboutToShow.emit()
        return [action.text() for action in menu.actions()]

    assert menu_of(layout)[:2] == ["default    the top-level strips", "gaming"]
    assert menu_of(strip) == ["1    output Speaker", "2    apps Browser"]
    type_into(qtbot, strip.line, "2")
    # a number, the position in the list
    assert window.document.get(("strip", 0, "strip")) == 2
    assert window.preview.strips[0].face.look.label == "Browser"
    type_into(qtbot, layout.line, "gaming")
    assert menu_of(strip)[1] == "2    voip"
    # a name: an id
    type_into(qtbot, strip.line, "lamp")
    assert window.document.get(("strip", 0, "strip")) == "lamp"
    window.document.set(("strip", 0, "strip"), 2)
    strip.load()
    assert strip.line.text() == "2"


VOIP = (
    '[voip]\nprovider = "demo"\n'
    '[[strip]]\ntype = "voip"\nperson = "Ann"\ncollapse = true\n' + '[[strip]]\ntype = "voip"\ncollapse = true\n' * 8
)


def test_voip_strips_say_who_is_on_them(qtbot: QtBot, make_window: MakeWindow, path: Path, live_daemon: FakeLiveDaemon):
    path.write_text(VOIP)
    window = make_window(live_socket=live_daemon.path)
    # the preview prints whom a strip is for, or that it is one of the group
    assert [strip.look.printed for strip in window.preview.strips[:2]] == ["Ann", "voip group"]
    person = row(window, "person")
    assert person.chips.values == ["Ann"]
    menu_button = next(button for button in person.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    assert [action.text() for action in menu.actions()] == [
        "Nobody is in the voice chat right now, or the daemon does not run"
    ]

    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    saved = window.document.saved_config
    assert saved is not None
    voip = VoipState("demo", True, None, None, 2, ("Ann", "Bob"), ("Ann", "Bob", *[None] * 7))
    strips = tuple(strip_state(("Live", "")) for _ in range(8))
    live_daemon.send(
        Snapshot(
            fingerprint(saved),
            True,
            True,
            None,
            strips,
            voip=voip,
            placement=(0, 1, None, None, None, None, None, None),
        )
    )
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    texts = [button.text() for button in window.strip_list.buttons]
    assert texts[:3] == ["1 Ann · on 1", "2 voip: Bob · on 2", "3 voip · collapsed"]

    # the people of the voice chat are suggested
    window.select(1)
    person = row(window, "person")
    assert person.chips.values == []
    assert person.chips.input.placeholderText() == "Add… (none: part of the group)"
    menu_button = next(button for button in person.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    assert [action.text() for action in menu.actions()] == [
        "Ann    in the voice chat now",
        "Bob    in the voice chat now",
    ]
    menu.actions()[1].trigger()
    assert window.document.get(("strip", 1, "person")) == ["Bob"]
    # the label shown by default follows
    assert row(window, "label").line.placeholderText() == "Bob"
    assert window.preview.strips[1].look.printed == "Bob"
