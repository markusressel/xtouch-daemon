"""
The fields of the forms.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDoubleSpinBox, QToolButton
from pytestqt.qtbot import QtBot

from tests.support.gui import MakeWindow, click, row, show_channel, type_into
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.chips import Chips
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def test_numbers_switches_and_choices(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    spin = row(window, "encoder_step", "behavior").spin
    spin.setValue(3)
    assert window.document.get(("behavior", "encoder_step")) == 3

    hold = row(window, "hold").spin
    assert isinstance(hold, QDoubleSpinBox)
    hold.setValue(2.5)
    assert window.document.get(("pool", "apps", "hold")) == 2.5
    # a number without a default: a step below the minimum is "not set"
    show_channel(window, "out")
    absent = row(window, "absent_after").spin
    assert isinstance(absent, QDoubleSpinBox)
    assert absent.specialValueText() == "default: not set"
    absent.setValue(1.5)
    assert window.document.get(("channel", "out", "absent_after")) == 1.5
    absent.setValue(absent.minimum())
    assert window.document.get(("channel", "out", "absent_after")) is None

    meters = row(window, "meters", "behavior")
    click(qtbot, meters.switch)
    assert window.document.get(("behavior", "meters")) is False
    assert not meters.reset.isHidden()

    click(qtbot, meters.reset)
    assert window.document.get(("behavior", "meters")) is None
    assert meters.switch.isChecked()

    rec = row(window, "rec")
    rec.combo.setCurrentText("muted")
    assert window.document.get(("channel", "out", "rec")) == "muted"


def test_switches_and_swatches_show_focus_and_disabled(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    switch = row(window, "meters", "behavior").switch
    show_channel(window, "out")
    swatch = row(window, "color").colors.swatches["red"]
    plain = (switch.grab().toImage(), swatch.grab().toImage())
    window.activateWindow()

    for widget, before in zip((switch, swatch), plain, strict=True):
        widget.setFocus()
        qtbot.waitUntil(widget.hasFocus)
        assert widget.grab().toImage() != before
    switch.setEnabled(False)
    assert switch.grab().toImage() != plain[0]


def test_colors_are_swatches(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    color = row(window, "color")
    assert color.colors.swatches["cyan"].isChecked()

    click(qtbot, color.colors.swatches["off"])

    assert window.document.get(("channel", "out", "color")) == "off"
    # the chosen one has a tick
    assert not color.colors.swatches["off"].grab().isNull()
    # a value that is no color checks none
    color.colors.show_value("pink")
    assert not any(swatch.isChecked() for swatch in color.colors.swatches.values())
    assert not color.colors.grab().isNull()


def test_a_list_is_chips(qtbot: QtBot, window: MainWindow):
    show_channel(window, "browser")
    chips: Chips = row(window, "match").chips

    type_into(qtbot, chips.input, "firefox")
    qtbot.keyClick(chips.input, Qt.Key.Key_Return)
    chips.add("firefox")
    chips.add("")
    assert window.document.get(("channel", "browser", "match")) == ["brave", "firefox"]

    chips.remove(0)
    assert window.document.get(("channel", "browser", "match")) == ["firefox"]
    assert chips.values == ["firefox"]
    # a chip, the input and the suggestions flow in the layout
    assert chips.flow.count() == 3


def test_a_list_without_suggestions_has_no_menu(qtbot: QtBot):
    chips = Chips(None)
    qtbot.addWidget(chips)
    # the input alone
    assert chips.flow.count() == 1
    assert chips.input.completer() is None


def test_suggestions_come_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    device = row(window, "device")
    menu_button = next(button for button in device.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    texts = [action.text() for action in menu.actions()]
    assert texts == ["speaker    speaker description (the default)", "buds    buds description"]
    menu.actions()[1].trigger()

    # added to the one of the file, which stood alone
    assert window.document.get(("channel", "out", "device")) == ["speaker", "buds"]
    assert device.chips.values == ["speaker", "buds"]


def test_an_empty_suggestion_list_says_so(make_window: MakeWindow):
    window = make_window(lambda: AudioState())
    show_channel(window, "out")
    menu_button = next(button for button in row(window, "device").findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    (action,) = menu.actions()
    assert action.text() == "The sound server has none right now"
    assert not action.isEnabled()


def test_a_list_of_applications_suggests_presets_first(window: MainWindow):
    show_channel(window, "browser")
    match = row(window, "match")
    menu_button = next(button for button in match.findChildren(QToolButton) if button.menu())
    assert menu_button.toolTip() == "Pick a preset, or from what the sound server has now"
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    actions = menu.actions()
    assert [action.text() for action in actions if action.isSeparator()] == ["Presets", "Names"]
    browsers = next(action for action in actions if action.text().startswith("@browsers"))
    assert browsers.text() == "@browsers    Web browsers"
    assert browsers.toolTip().startswith("Web browsers: firefox, librewolf, ")
    named = actions[[action.text() for action in actions].index("Names") + 1]
    # a name of the sound server: the tip is the text
    assert named.toolTip() == named.text()

    browsers.trigger()
    assert window.document.get(("channel", "browser", "match")) == ["brave", "@browsers"]
    chip = match.chips.chips[1]
    assert chip.property("variant") == "preset"
    assert chip.toolTip().startswith("Web browsers: firefox")
    assert match.chips.chips[0].property("variant") is None


def test_a_list_of_processes_suggests_the_presets_for_processes(qtbot: QtBot):
    chips = Chips(None, presets=PresetKind.PROCESSES)
    qtbot.addWidget(chips)
    chips.show_values(["@browsers", "@nope", "steam"])

    # the presets, though the sound server has nothing for processes
    assert chips.input.completer() is not None
    assert (
        chips.chips[0]
        .toolTip()
        .startswith("Web browsers: firefox, librewolf, floorp, waterfox, zen-bin, chromium, brave")
    )
    # an unknown preset and a name are plain chips: validation tells what is wrong
    assert [chip.property("variant") for chip in chips.chips[1:]] == [None, None]


def test_typing_completes_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    device = row(window, "device")
    click(qtbot, device.chips.chips[0].findChild(QToolButton))
    assert window.document.get(("channel", "out", "device")) is None
    assert device.chips.input.placeholderText() == "Add… (none: the default output)"

    type_into(qtbot, device.chips.input, "bu")
    completer = device.chips.input.completer()
    assert completer is not None
    assert completer.model().stringList() == ["speaker", "buds"]  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]

    completer.activated.emit("buds")
    assert window.document.get(("channel", "out", "device")) == ["buds"]


def test_a_text_can_be_picked_from_suggestions(qtbot: QtBot):
    put: list[object] = []
    text = OptionRow(
        Option("name", Kind.TEXT, "", None, False), lambda: 3, put.append, lambda: (Suggestion("ann", "Ann"),)
    )
    qtbot.addWidget(text)
    # a value that is no text shows none
    assert text.line.text() == ""
    menu_button = next(button for button in text.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()
    menu.actions()[0].trigger()
    assert put == ["ann"]
