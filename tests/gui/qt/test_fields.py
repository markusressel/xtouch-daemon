"""
The fields of the forms.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDoubleSpinBox, QToolButton
from pytestqt.qtbot import QtBot

from tests.support.gui import MakeWindow, click, row, type_into
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.qt.fields.chips import Chips
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def test_numbers_switches_and_choices(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    spin = row(window, "encoder_step", "behavior").spin
    spin.setValue(3)
    assert window.document.get(("behavior", "encoder_step")) == 3

    hold = row(window, "auto_hold", "behavior").spin
    assert isinstance(hold, QDoubleSpinBox)
    hold.setValue(2.5)
    assert window.document.get(("behavior", "auto_hold")) == 2.5

    meters = row(window, "meters", "behavior")
    click(qtbot, meters.switch)
    assert window.document.get(("behavior", "meters")) is False
    assert not meters.reset.isHidden()

    click(qtbot, meters.reset)
    assert window.document.get(("behavior", "meters")) is None
    assert meters.switch.isChecked()

    rec = row(window, "rec")
    rec.combo.setCurrentText("muted")
    assert window.document.get(("strip", 0, "rec")) == "muted"


def test_switches_and_swatches_show_focus_and_disabled(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    switch = row(window, "meters", "behavior").switch
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
    color = row(window, "color")
    assert color.colors.swatches["cyan"].isChecked()

    click(qtbot, color.colors.swatches["off"])

    assert window.document.get(("strip", 0, "color")) == "off"
    assert window.preview.strips[0].look.color == "off"
    # the chosen one has a tick
    assert not color.colors.swatches["off"].grab().isNull()
    # a value that is no color checks none
    color.colors.show_value("pink")
    assert not any(swatch.isChecked() for swatch in color.colors.swatches.values())
    assert not color.colors.grab().isNull()


def test_a_list_is_chips(qtbot: QtBot, window: MainWindow):
    window.select(1)
    chips: Chips = row(window, "match").chips

    type_into(qtbot, chips.input, "firefox")
    qtbot.keyClick(chips.input, Qt.Key.Key_Return)
    chips.add("firefox")
    chips.add("")
    assert window.document.get(("strip", 1, "match")) == ["brave", "firefox"]

    chips.remove(0)
    assert window.document.get(("strip", 1, "match")) == ["firefox"]
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
    device = row(window, "device")
    menu_button = next(button for button in device.findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    texts = [action.text() for action in menu.actions()]
    assert texts == ["speaker    speaker description (the default)", "buds    buds description"]
    menu.actions()[1].trigger()

    # added to the one of the file, which stood alone
    assert window.document.get(("strip", 0, "device")) == ["speaker", "buds"]
    assert device.chips.values == ["speaker", "buds"]


def test_an_empty_suggestion_list_says_so(make_window: MakeWindow):
    window = make_window(lambda: AudioState())
    menu_button = next(button for button in row(window, "device").findChildren(QToolButton) if button.menu())
    menu = menu_button.menu()
    assert menu is not None
    menu.aboutToShow.emit()

    (action,) = menu.actions()
    assert action.text() == "The sound server has none right now"
    assert not action.isEnabled()


def test_a_list_of_applications_suggests_presets_first(window: MainWindow):
    window.select(1)
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
    assert window.document.get(("strip", 1, "match")) == ["brave", "@browsers"]
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
    device = row(window, "device")
    click(qtbot, device.chips.chips[0].findChild(QToolButton))
    assert window.document.get(("strip", 0, "device")) is None
    assert device.chips.input.placeholderText() == "Add… (none: the default output)"

    type_into(qtbot, device.chips.input, "bu")
    completer = device.chips.input.completer()
    assert completer is not None
    assert completer.model().stringList() == ["speaker", "buds"]  # pyright: ignore[reportOptionalMemberAccess, reportAttributeAccessIssue]

    completer.activated.emit("buds")
    assert window.document.get(("strip", 0, "device")) == ["buds"]


def test_an_unset_label_shows_the_default(qtbot: QtBot, window: MainWindow):
    label = row(window, "label")
    click(qtbot, label.reset)

    assert window.document.get(("strip", 0, "label")) is None
    assert label.line.placeholderText() == "speaker"
    # the device decides the default label, like on the device: the start of its description, or the type
    window.document.set(("strip", 0, "device"), ["buds"])
    label.load()
    assert label.line.placeholderText() == "buds de"
    window.document.unset(("strip", 0, "device"))
    label.load()
    assert label.line.placeholderText() == "Output"
