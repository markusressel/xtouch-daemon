"""
The fields of the forms.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDoubleSpinBox
from pytestqt.qtbot import QtBot

from tests.support.gui import MakeWindow, click, row, show_channel, type_into
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.gui.domain.schema import Kind, Option
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.chips import Chips
from xtouch_daemon.gui.qt.fields.names import SUGGESTION_ROLE, NameCompleter, suggestion_html
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def test_numbers_switches_and_choices(qtbot: QtBot, window: MainWindow):
    window.show_page("behavior")
    spin = row(window, "encoder_step", "behavior").spin
    spin.setValue(3)
    assert window.document.get(("behavior", "encoder_step")) == 3

    window.channels_page.select(("pool", "apps"))
    hold = row(window, "hold").spin
    assert isinstance(hold, QDoubleSpinBox)
    hold.setValue(2.5)
    assert window.document.get(("pool", "apps", "hold")) == 2.5
    # a number with a default shows it
    show_channel(window, "out")
    absent = row(window, "absent_after").spin
    assert isinstance(absent, QDoubleSpinBox)
    assert absent.value() == 3
    absent.setValue(1.5)
    assert window.document.get(("channel", "out", "absent_after")) == 1.5

    meters = row(window, "meters", "behavior")
    click(qtbot, meters.switch)
    assert window.document.get(("behavior", "meters")) is False
    assert not meters.reset.isHidden()

    click(qtbot, meters.reset)
    assert window.document.get(("behavior", "meters")) is None
    assert meters.switch.isChecked()

    rec = row(window, "rec").buttons
    rec.combos["led"].setCurrentText("muted")
    # the LED alone: the short form
    assert window.document.get(("channel", "out", "rec")) == "muted"
    rec.combos["press"].setEditText("mute_others")
    assert window.document.get(("channel", "out", "rec")) == {"press": "mute_others", "led": "muted"}


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
    # a chip and the input flow in the layout
    assert chips.flow.count() == 2


def test_a_list_without_suggestions_suggests_nothing(qtbot: QtBot):
    chips = Chips(None)
    qtbot.addWidget(chips)
    # the input alone
    assert chips.flow.count() == 1
    assert chips.completer is None


def listed(completer: NameCompleter | None, text: str = "") -> list[str]:
    """What the list of a completer shows for `text`."""
    assert completer is not None
    completer.fill(text)
    return [str(completer.items.index(line, 0).data()) for line in range(completer.items.rowCount())]


def added_device(device: OptionRow) -> OptionRow:
    """The device field of a new entry of the list of devices."""
    device.tables.add()
    return device.tables.entries[-1].rows["device"]


def test_suggestions_come_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    device = row(window, "device")
    completer = added_device(device).completer
    assert listed(completer) == ["speaker", "buds"]
    assert completer is not None
    # what each is, where it is known from, and the name below
    first = completer.items.item(0)
    assert first is not None
    shown = suggestion_html(first.data(SUGGESTION_ROLE), "")
    assert "speaker description" in shown
    assert "· default" in shown
    completer.activated.emit("buds")

    # added to the one of the file, which stood alone
    assert window.document.get(("channel", "out", "device")) == ["speaker", "buds"]
    assert [entry.title.text() for entry in device.tables.entries] == ["speaker description", "buds description"]


def test_an_empty_suggestion_list_says_so(make_window: MakeWindow):
    window = make_window(lambda: AudioState())
    show_channel(window, "out")
    completer = added_device(row(window, "device")).completer
    assert listed(completer) == ["The sound server has none right now"]
    assert completer is not None
    item = completer.items.item(0)
    assert item is not None
    assert not item.isEnabled()
    assert listed(completer, "x") == ["Nothing known matches 'x'"]


def test_a_list_of_applications_suggests_presets_first(window: MainWindow):
    show_channel(window, "browser")
    match = row(window, "match")
    completer = match.chips.completer
    shown = listed(completer)
    assert shown[0].startswith("@")
    assert "brave" in shown
    assert completer is not None
    browsers = completer.items.item(shown.index("@browsers"))
    assert browsers is not None
    assert browsers.toolTip().startswith("Web browsers: firefox, librewolf, ")

    completer.activated.emit("@browsers")
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
    assert chips.completer is not None
    assert (
        chips.chips[0]
        .toolTip()
        .startswith("Web browsers: firefox, librewolf, floorp, waterfox, zen-bin, chromium, brave")
    )
    # an unknown preset and a name are plain chips: validation tells what is wrong
    assert [chip.property("variant") for chip in chips.chips[1:]] == [None, None]

    # other values: the chips before go off the screen at once, not when the event loop deletes them
    chips.show()
    before = list(chips.chips)
    chips.show_values(["steam"])
    assert all(chip.isHidden() for chip in before)


def test_typing_completes_from_the_sound_server(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    device = row(window, "device")
    click(qtbot, device.tables.entries[0].remove_button)
    assert window.document.get(("channel", "out", "device")) is None
    field = added_device(device)

    type_into(qtbot, field.line, "bu")
    # narrowed down to what has the text, by name or description
    assert listed(field.completer, "bu") == ["buds"]
    assert listed(field.completer, "*des*") == ["speaker", "buds"]

    completer = field.completer
    assert completer is not None
    completer.activated.emit("buds")
    assert window.document.get(("channel", "out", "device")) == "buds"


def test_a_text_can_be_picked_from_suggestions(qtbot: QtBot):
    put: list[object] = []
    text = OptionRow(
        Option("device", Kind.TEXT, "", None, False), lambda: 3, put.append, lambda: (Suggestion("ann", "Ann"),)
    )
    qtbot.addWidget(text)
    # a value that is no text shows none
    assert text.line.text() == ""
    picked: list[Suggestion] = []
    text.picked.connect(picked.append)
    assert text.completer is not None
    text.completer.activated.emit("ann")
    assert put == ["ann"]
    assert picked == [Suggestion("ann", "Ann")]
    # what it matches, under the field
    assert text.matches.text() == "Matches Ann"
    type_into(qtbot, text.line, "bob")
    assert text.matches.text() == "Matches nothing known: it may come later"
    assert text.matches.property("role") == "warn"


def test_in_a_wide_row_the_reset_button_stays_beside_the_field(qtbot: QtBot):
    from xtouch_daemon.gui.domain.schema import strip_options
    from xtouch_daemon.gui.qt.fields.option_row import WIDEST_FIELD

    option = next(each for each in strip_options("output") if each.name == "label")
    option_row = OptionRow(option, lambda: "Speakers", lambda _value: None)
    qtbot.addWidget(option_row)
    option_row.resize(2000, 200)
    option_row.show()
    qtbot.waitExposed(option_row)
    qtbot.wait(1)  # the layout takes the new margins
    assert option_row.narrow is False
    beside = option_row.title_width + WIDEST_FIELD + 4 * 8
    assert option_row.field.width() <= WIDEST_FIELD
    assert option_row.reset.isVisible()
    assert option_row.reset.geometry().right() < beside + option_row.reset.width()
    assert option_row.help.geometry().right() <= option_row.reset.geometry().right()
    option_row.resize(500, 200)
    qtbot.wait(1)
    assert option_row.reset.geometry().right() <= option_row.width()
    assert option_row.width() < 2000


def test_a_number_without_a_default_is_not_set_in_gray(qapp: QApplication):
    values: dict[str, object] = {}
    option = Option("every", Kind.NUMBER, "", None, False)
    option_row = OptionRow(option, lambda: values.get("every"), lambda value: values.__setitem__("every", value))
    option_row.load()
    spin = option_row.spin
    assert isinstance(spin, QDoubleSpinBox)
    # a step below the minimum is "not set": what applies depends on something else, its help says what
    assert spin.specialValueText() == "not set"
    assert spin.property("unset") is True
    spin.setValue(1.5)
    assert values["every"] == 1.5
    assert spin.property("unset") is False
    spin.setValue(spin.minimum())
    assert values["every"] is None
    assert spin.property("unset") is True
