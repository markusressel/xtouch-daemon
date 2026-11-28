"""The fields of the forms in QML: each kind of option, edited the way a user does."""

from typing import Any

import pytest
from PyQt6.QtCore import Qt

from tests.gui.quick.forms_host import HostUi, host
from tests.gui.quick.test_forms import rows
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.forms.strips import channel_form, pool_form

OUT = ("channel", "out")


@pytest.fixture
def form(ui: Ui) -> Form:
    result = channel_form(forms_of(ui.app), "output")
    result.retarget(OUT)
    return result


@pytest.fixture
def hosted(ui: Ui, form: Form) -> HostUi:
    return host(ui, form)


def value(ui: Ui, *path: str) -> Any:
    return ui.app.editor.document.get((*OUT, *path))


def test_a_text_is_typed_and_reset(hosted: HostUi, ui: Ui):
    hosted.focus("field_label")
    hosted.item("field_label").setProperty("text", "")
    hosted.type("Desk")
    assert value(ui, "label") == "Desk"
    hosted.click("reset_label")
    assert value(ui, "label") is None
    assert hosted.text("field_label") == ""


def test_a_switch_is_toggled(hosted: HostUi, ui: Ui):
    hosted.click("switch_lit_when_idle")
    assert value(ui, "lit_when_idle") is True
    assert hosted.item("switch_lit_when_idle").property("checked") is True
    hosted.click("reset_lit_when_idle")
    assert value(ui, "lit_when_idle") is None
    assert hosted.item("switch_lit_when_idle").property("checked") is False


def test_a_color_is_picked_from_the_swatches(hosted: HostUi, ui: Ui):
    hosted.click("color_red")
    assert value(ui, "color") == "red"
    assert hosted.item("color_red").property("picked") is True
    assert hosted.item("color_cyan").property("picked") is False


def test_a_choice_is_picked_from_its_list(hosted: HostUi, ui: Ui):
    hosted.click("choice_mute_led")
    hosted.wait_until(lambda: hosted.shows("choice_item_flash"))
    hosted.click("choice_item_flash")
    assert value(ui, "mute_led") == "flash"
    assert hosted.item("choice_mute_led").property("currentText") == "flash"


def test_an_entry_of_devices_is_added_opened_and_removed(hosted: HostUi, ui: Ui):
    assert hosted.shows("entry_device_0")
    hosted.click("add_device")
    hosted.wait_until(lambda: hosted.find("entry_device_1") is not None)
    # a new entry is not in the file until it has something in it
    assert value(ui, "device") == "speaker"
    hosted.click("remove_1")
    hosted.wait_until(lambda: hosted.find("entry_device_1") is None)
    hosted.click("remove_0")
    assert value(ui, "device") is None


def test_entries_of_devices_move_with_the_keys(hosted: HostUi, ui: Ui, form: Form):
    form.setValue("device", [{"device": "speaker"}, {"device": "buds"}])
    hosted.settle()
    hosted.focus("entry_device_0")
    hosted.key(Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert value(ui, "device") == ["buds", "speaker"]


def test_the_options_of_an_entry_open_one_at_a_time(hosted: HostUi, ui: Ui, form: Form):
    form.setValue("device", [{"device": "speaker"}, {"device": "buds"}])
    hosted.settle()
    hosted.click("edit_0")
    hosted.click("edit_1")
    assert hosted.item("entry_device_1").property("open") is True
    assert hosted.item("entry_device_0").property("open") is False


def test_a_button_part_is_picked_from_its_list(hosted: HostUi, ui: Ui):
    hosted.click("button_rec_led_text")
    hosted.wait_until(lambda: hosted.shows("suggestion_recording"))
    hosted.click("suggestion_recording")
    assert value(ui, "rec") == "recording"


def test_a_part_is_bound_to_a_program(hosted: HostUi, ui: Ui):
    hosted.click("bind_color")
    hosted.wait_until(lambda: hosted.shows("bind_to_program"))
    hosted.click("bind_to_program")
    assert isinstance(value(ui, "color"), dict)
    hosted.click("bind_color")
    hosted.wait_until(lambda: hosted.shows("bind_to_words"))
    hosted.click("bind_to_words")
    assert value(ui, "color") is None


def test_rows_show_a_problem_below_them(hosted: HostUi, ui: Ui):
    ui.app.editor.document.set((*OUT, "absent_after"), "soon")
    ui.app.editor.edited()
    hosted.settle()
    assert hosted.shows("problem_absent_after")


def test_a_number_is_typed_stepped_and_cleared(ui: Ui):
    form = pool_form(forms_of(ui.app), "apps")
    form.retarget(("pool", "apps"))
    hosted = host(ui, form)
    hosted.focus("field_hold")
    hosted.item("field_hold").setProperty("text", "")
    hosted.type("2")
    assert ui.app.editor.document.get(("pool", "apps", "hold")) == 2
    hosted.key(Qt.Key.Key_Up)
    assert ui.app.editor.document.get(("pool", "apps", "hold")) == 2.5


def test_a_list_adds_and_removes_chips(ui: Ui):
    form = pool_form(forms_of(ui.app), "apps")
    form.retarget(("pool", "apps"))
    hosted = host(ui, form)
    names = [name for name, row in rows(form).items() if row["spec"]["kind"] == "list"]
    assert names
    name = names[0]
    hosted.focus(f"add_{name}")
    hosted.type("firefox")
    hosted.key(Qt.Key.Key_Return)
    assert "firefox" in (ui.app.editor.document.get(("pool", "apps", name)) or [])
    assert hosted.shows("chip_firefox")
    hosted.click("chip_remove_firefox")
    assert "firefox" not in (ui.app.editor.document.get(("pool", "apps", name)) or [])
