"""
Parts bound to Home Assistant or to programs of your own in the forms of channels: the field of the words as without
bindings, a button that binds, the options of the program below, and what that writes to the file.
"""

import tomllib

import pytest
from PyQt6.QtWidgets import QDoubleSpinBox, QLabel, QWidget
from pytestqt.qtbot import QtBot

from tests.support.gui import plain, row, show_channel, shows
from xtouch_daemon.gui.domain.schema import Kind, strip_options
from xtouch_daemon.gui.qt.fields.binding import HOME_ASSISTANT, PROGRAM, WORDS, BindingField
from xtouch_daemon.gui.qt.fields.option_row import OptionRow
from xtouch_daemon.gui.qt.window.main_window import MainWindow

SET = ["sysctrl", "display", "redshift", "brightness", "-d", "DisplayPort-1", "-b", "{value}"]


def add_custom(window: MainWindow) -> None:
    window.show_page("channels")
    window.channels_page.add("custom")
    assert window.channels_page.selection == ("channel", "custom")


def binding(option_row: OptionRow) -> BindingField:
    assert option_row.option.kind == Kind.BINDING
    return option_row.binding


def written(window: MainWindow, *path: str) -> object:
    """What the file says at `path`, as the editor writes it."""
    value: object = tomllib.loads(window.document.render())
    for key in path:
        assert isinstance(value, dict)
        value = value.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return value


def number(option_row: OptionRow) -> QDoubleSpinBox:
    assert isinstance(option_row.spin, QDoubleSpinBox)
    return option_row.spin


def visible(widget: QWidget, window: MainWindow) -> bool:
    return shows(widget, window)


def help_of(field: BindingField) -> str:
    """The help under the row of `field`, as it reads: its default at the end."""
    parent = field.parentWidget()
    while not isinstance(parent, OptionRow):
        assert parent is not None
        parent = parent.parentWidget()
    return words(parent.help)


def words(shown: QLabel) -> str:
    """The text of a label as it reads, its spaces as one."""
    return " ".join(plain(shown.text()).split())


def test_a_fader_bound_to_a_program_writes_its_table(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    fader = row(window, "fader")
    field = binding(fader)
    # not bound: what the strip does without it, and a button to bind it
    assert not visible(field.program, window)
    assert words(field.unbound) == "not bound"
    assert "DEFAULT none: the fader stays down " in help_of(field) + " "
    assert field.bind.text() == ""
    assert [action.text() for action in field.menu.actions() if action.isVisible()] == [
        "Home Assistant",
        "An entity",
        "A program",
    ]
    field.actions_[PROGRAM].trigger()
    assert window.document.get(("channel", "custom", "fader")) == {}
    assert visible(field.program, window)
    assert field.bind.text() == "A program"
    assert field.actions_[WORDS].isVisible()
    assert "A value that programs of your own set and watch" in plain(field.program.findChildren(QWidget)[0].text())  # pyright: ignore[reportAttributeAccessIssue]
    # the options of the program, each a row
    assert list(field.rows) == ["set", "watch", "poll", "every", "min", "max", "step", "format"]
    for part in SET:
        field.rows["set"].chips.add(part)
    number(field.rows["min"]).setValue(0.1)
    number(field.rows["max"]).setValue(1.0)
    field.rows["format"].line.setText("{value:.0%}")
    field.rows["format"].line.textEdited.emit("{value:.0%}")
    assert written(window, "channel", "custom", "fader") == {
        "set": SET,
        "min": 0.1,
        "max": 1.0,
        "format": "{value:.0%}",
    }
    assert window.document.validate().at("channel", "custom") == []
    # numbers of your own: finer, any sign; unset ones say what they do
    assert number(field.rows["min"]).decimals() == 3
    assert number(field.rows["min"]).minimum() < 0
    assert number(field.rows["step"]).specialValueText() == "default: behavior.encoder_step % of the range"
    # loaded again, the form shows the file
    fader.load()
    assert field.rows["set"].chips.values == SET
    assert number(field.rows["max"]).value() == 1.0
    # back: not bound, the default
    field.actions_[WORDS].trigger()
    assert window.document.get(("channel", "custom", "fader")) is None
    assert not visible(field.program, window)
    # bound again: the options it had
    field.actions_[PROGRAM].trigger()
    assert window.document.get(("channel", "custom", "fader"))["set"] == SET


def test_a_problem_of_the_program_shows_under_its_part(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    field = binding(row(window, "fader"))
    field.actions_[PROGRAM].trigger()
    field.rows["set"].chips.add("brightness")
    window.editor.edited()
    problems = window.document.validate().at("channel", "custom")
    assert any("value goes nowhere" in problem.message for problem in problems)
    fader = row(window, "fader")
    # under the option of the program that has it
    set_row = binding(fader).rows["set"]
    assert visible(set_row.error, window)
    assert "no argument has {value}" in set_row.error.text()
    assert not visible(fader.error, window)


def test_a_part_bound_to_home_assistant(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    field = binding(row(window, "fader"))
    field.actions_[HOME_ASSISTANT].trigger()
    assert window.document.get(("channel", "custom", "fader")) == "homeassistant"
    assert field.bind.text() == "Home Assistant"
    assert field.actions_[HOME_ASSISTANT].isChecked()
    assert not visible(field.program, window)
    # what it means, under the field
    fader = row(window, "fader")
    assert "number entity in Home Assistant" in plain(fader.meaning.text())


def test_an_audio_strip_looks_as_before_until_a_part_is_bound(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    fader = row(window, "fader")
    field = binding(fader)
    # the list of the fader, as without bindings, with homeassistant in it
    assert fader.combo is field.combo
    assert [fader.combo.itemText(index) for index in range(fader.combo.count())] == ["volume", "homeassistant"]
    assert fader.combo.currentText() == "volume"
    assert visible(fader.combo, window)
    assert field.bind.text() == ""
    encoder = row(window, "encoder")
    assert encoder.combo.placeholderText() == "default: balance"
    fader.combo.setCurrentText("homeassistant")
    assert window.document.get(("channel", "out", "fader")) == "homeassistant"
    # the fader does not set the volume: the encoder does
    assert encoder.combo.placeholderText() == "default: volume"
    assert "volume" in plain(encoder.meaning.text())
    # homeassistant is in the list: the button stays a button
    assert field.bind.text() == ""
    field.actions_[PROGRAM].trigger()
    assert not visible(fader.combo, window)
    field.rows["set"].chips.add("light")
    field.rows["set"].chips.add("{value}")
    assert written(window, "channel", "out", "fader") == {"set": ["light", "{value}"]}
    # a fader bound away from the volume gives the volume to the encoder: the file is fine
    assert window.document.validate().at("channel", "out") == []


def test_colors_stay_swatches_and_can_be_bound(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    color = row(window, "color")
    field = binding(color)
    assert color.colors is field.colors
    assert color.colors.swatches["cyan"].isChecked()
    assert "homeassistant" not in color.colors.swatches
    color.colors.swatches["red"].click()
    assert window.document.get(("channel", "out", "color")) == "red"
    field.actions_[HOME_ASSISTANT].trigger()
    assert window.document.get(("channel", "out", "color")) == "homeassistant"
    assert not visible(color.colors, window)
    assert field.bind.text() == "Home Assistant"
    field.actions_[PROGRAM].trigger()
    field.rows["watch"].chips.add("color-of-the-day")
    assert written(window, "channel", "out", "color") == {"watch": ["color-of-the-day"]}
    # unset: the default color again
    color.reset.click()
    assert window.document.get(("channel", "out", "color")) is None
    assert visible(color.colors, window)
    assert color.colors.swatches["white"].isChecked()


def test_the_meter_of_an_audio_strip_is_a_choice_or_bound(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    meter = row(window, "meter")
    field = binding(meter)
    assert [meter.combo.itemText(index) for index in range(meter.combo.count())] == ["pre_fader", "post_fader", "off"]
    meter.combo.setCurrentText("off")
    assert window.document.get(("channel", "out", "meter")) is False
    field.actions_[PROGRAM].trigger()
    field.rows["watch"].chips.add("cpu-load")
    number(field.rows["max"]).setValue(4.0)
    assert written(window, "channel", "out", "meter") == {"watch": ["cpu-load"], "max": 4.0}
    # a level in dB, below 0
    number(field.rows["min"]).setValue(-60.25)
    assert window.document.get(("channel", "out", "meter"))["min"] == -60.25
    assert window.document.get(("channel", "out", "meter_point")) is None
    meter.load()
    assert field.mode == PROGRAM
    field.actions_[HOME_ASSISTANT].trigger()
    assert window.document.get(("channel", "out", "meter")) == "homeassistant"
    meter.load()
    assert field.bind.text() == "Home Assistant"
    field.actions_[WORDS].trigger()
    assert window.document.get(("channel", "out", "meter")) is None


def test_a_custom_meter_lcd_and_presence_are_bound_or_not_set(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    meter = binding(row(window, "meter"))
    assert words(meter.unbound) == "not bound"
    assert "DEFAULT none: the meter stays dark " in help_of(meter) + " "
    lcd = binding(row(window, "lcd"))
    assert words(lcd.unbound) == "not bound"
    assert "DEFAULT the value of the fader, else of the encoder " in help_of(lcd) + " "
    present = binding(row(window, "present"))
    # a program only: no Home Assistant
    assert HOME_ASSISTANT not in present.actions_
    present.actions_[PROGRAM].trigger()
    assert {"watch", "poll", "every"} <= set(present.rows)
    present.rows["watch"].chips.add("screen-connected")
    present.rows["watch"].chips.add("--watch")
    assert written(window, "channel", "custom", "present") == {"watch": ["screen-connected", "--watch"]}


def test_the_lcd_of_an_audio_strip_says_what_it_shows_unbound(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    lcd = binding(row(window, "lcd"))
    assert words(lcd.unbound) == "not bound"
    assert "DEFAULT what the type shows " in help_of(lcd) + " "
    lcd.actions_[HOME_ASSISTANT].trigger()
    assert window.document.get(("channel", "out", "lcd")) == "homeassistant"
    assert words(lcd.unbound) == ""


def test_targets_are_a_table_of_names_and_values(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    targets = row(window, "targets")
    assert targets.option.kind == Kind.TABLES
    assert [column.name for column in targets.option.columns] == ["name", "value"]
    assert row(window, "together").option.kind == Kind.SWITCH
    # the buttons of a custom channel: Mute too, and they do nothing unless told
    mute = row(window, "mute")
    assert mute.buttons.combos["press"].lineEdit().placeholderText() == "default: off"  # pyright: ignore[reportOptionalMemberAccess]
    choices = [mute.buttons.combos["press"].itemText(i) for i in range(mute.buttons.combos["press"].count())]
    assert "default" not in choices
    assert {"off", "next", "cycle_modes", "homeassistant"} <= set(choices)


def test_buttons_run_programs_and_leds_watch_them(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    select = row(window, "select")
    combos = select.buttons.combos
    combos["press"].setEditText("run: sysctrl display reset --name 'Left screen'")
    assert window.document.get(("channel", "custom", "select")) == {
        "press": {"run": ["sysctrl", "display", "reset", "--name", "Left screen"]}
    }
    combos["led"].setEditText("watch: screen-state --follow")
    assert written(window, "channel", "custom", "select") == {
        "press": {"run": ["sysctrl", "display", "reset", "--name", "Left screen"]},
        "led": {"watch": ["screen-state", "--follow"]},
    }
    assert "Runs the program to its end." in plain(select.buttons.meaning.text())
    assert "Lit while the program's newest line" in plain(select.buttons.meaning.text())
    # loaded again: the tables as text, kept as they are
    select.load()
    assert combos["press"].currentText() == "run: sysctrl display reset --name 'Left screen'"
    assert combos["led"].currentText() == "watch: screen-state --follow"
    combos["hold"].setEditText("cycle_modes")
    assert window.document.get(("channel", "custom", "select"))["press"] == {
        "run": ["sysctrl", "display", "reset", "--name", "Left screen"]
    }
    # an open quote: split at the spaces, the problem says what is wrong
    combos["press"].setEditText("run: say 'hi")
    assert window.document.get(("channel", "custom", "select"))["press"] == {"run": ["say", "'hi"]}
    # a poll instead of the watch
    combos["led"].setEditText("poll: screen-state")
    assert window.document.get(("channel", "custom", "select"))["led"] == {"poll": ["screen-state"]}
    assert "Lit while the last line of the program's last run" in plain(select.buttons.meaning.text())


def test_a_place_takes_only_the_words_of_a_part(qtbot: QtBot, window: MainWindow):
    window.show_page("slots")
    page = window.slots_page
    window.device_view.select(0)
    by_name = {option_row.option.name: option_row for option_row in page.place_rows}
    # bindings belong to the channel
    assert by_name["meter"].option.kind == Kind.CHOICE
    assert by_name["color"].option.kind == Kind.COLOR


def test_a_part_that_is_a_switch_or_bound(qtbot: QtBot):
    meter = next(option for option in strip_options("output") if option.name == "meter")
    field = BindingField(meter)
    qtbot.addWidget(field)
    values: list[object] = []
    field.changed.connect(values.append)
    field.show_value(None)
    # unset: the default, on
    assert field.switch.isChecked()
    assert field.word() is True
    field.switch.click()
    assert values == [False]
    field.show_value({"watch": ["cpu-load"]})
    assert field.word() is None
    assert field.mode == PROGRAM
    assert field.switch.isHidden()


def test_a_step_up_from_unset_starts_inside_the_range(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    field = binding(row(window, "encoder"))
    field.actions_[PROGRAM].trigger()
    for part in SET:
        field.rows["set"].chips.add(part)
    number(field.rows["min"]).setValue(0.1)
    number(field.rows["max"]).setValue(1.0)
    # unset, a step up goes to the bottom of the range, not a step away from far below it
    number(field.rows["push"]).stepBy(1)
    assert window.document.get(("channel", "custom", "encoder"))["push"] == 0.1
    # a step: one step of the encoder by default (`behavior.encoder_step` percent of the range)
    number(field.rows["step"]).stepBy(1)
    assert window.document.get(("channel", "custom", "encoder"))["step"] == pytest.approx(0.009)
    assert window.document.validate().at("channel", "custom") == []
    # set, it steps as any number
    number(field.rows["push"]).stepBy(1)
    assert window.document.get(("channel", "custom", "encoder"))["push"] > 0.1


def test_the_numbers_of_the_daemon_keep_their_minimum(qtbot: QtBot, window: MainWindow):
    window.show_page("states")
    spin = number(row(window, "delay_off", "states"))
    assert (spin.minimum(), spin.decimals()) == (-0.5, 1)
    spin.stepBy(1)
    assert window.document.get(("state", "call", "delay_off")) == 0


def test_a_problem_of_an_option_of_the_program_shows_under_that_option(qtbot: QtBot, window: MainWindow):
    add_custom(window)
    field = binding(row(window, "fader"))
    field.actions_[PROGRAM].trigger()
    for part in SET:
        field.rows["set"].chips.add(part)
    number(field.rows["min"]).setValue(5)
    number(field.rows["max"]).setValue(2)
    window.editor.edited()
    fader = row(window, "fader")
    field = binding(fader)
    assert "is not above min" in field.rows["max"].error.text()
    assert visible(field.rows["max"].error, window)
    assert not visible(field.rows["min"].error, window)
    assert not visible(fader.error, window)


def test_parts_that_cant_be_bound_have_no_bind_button(qtbot: QtBot, window: MainWindow):
    # the meter of a person, and of a built-in pool: their words only
    window.show_page("channels")
    window.channels_page.add("person")
    assert row(window, "meter").option.kind != Kind.BINDING
    window.channels_page.select(("pool", "apps"))
    assert row(window, "meter").option.kind != Kind.BINDING
    # the LEDs of the buttons of a pool: a list of words, not to type into, without homeassistant
    led = row(window, "rec").buttons.combos["led"]
    assert not led.isEditable()
    assert "homeassistant" not in [led.itemText(index) for index in range(led.count())]
    # an output's meter can be bound
    show_channel(window, "out")
    assert row(window, "meter").option.kind == Kind.BINDING


def test_an_led_in_the_file_loads_and_saves_unchanged(qtbot: QtBot, window: MainWindow):
    show_channel(window, "out")
    window.document.set(("channel", "out", "rec"), "muted")
    rec = row(window, "rec")
    rec.load()
    assert rec.buttons.combos["led"].currentText() == "muted"
    assert rec.buttons.value() == "muted"
    # an LED that means nothing: shown as it is, its problem under the row
    window.document.set(("channel", "out", "rec"), {"led": "blinking"})
    window.editor.edited()
    rec = row(window, "rec")
    rec.load()
    assert rec.buttons.combos["led"].currentText() == "blinking"
    assert rec.buttons.value() == "blinking"
    assert visible(rec.error, window)
