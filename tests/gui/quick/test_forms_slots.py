"""What QML calls on a form and its context: lists of devices, buttons, suggestions, presets, used-by and history."""

import time
from typing import Any

import pytest

from tests.gui.quick.test_forms import out, rows  # noqa: F401  (the fixture)
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.forms.strips import pool_form


def suggested(form: Form, key: str, text: str = "", line: dict[str, Any] | None = None) -> list[str]:
    return [row["value"] for row in form.suggestions(key, line or {}, text, "dark")["rows"]]


def test_the_devices_are_suggested_from_the_sound_server(ui: Ui, out: Form):  # noqa: F811
    ui.wait_until(lambda: bool(forms_of(ui.app).audio().outputs))
    values = suggested(out, "device.device")
    assert "speaker" in values
    assert "buds" in values
    assert suggested(out, "device.device", "bud") == ["buds"]


def test_a_device_in_another_profile_gives_its_card_and_profile(ui: Ui, out: Form):  # noqa: F811
    ui.wait_until(lambda: bool(forms_of(ui.app).audio().outputs))
    assert out.picked("device.device", {}, "speaker") == {}


def test_an_unknown_key_suggests_nothing(out: Form):  # noqa: F811
    assert out.suggestions("nonsense", {}, "", "dark")["rows"] == []


def test_the_presets_of_a_list_come_first(ui: Ui):
    form = pool_form(forms_of(ui.app), "apps")
    form.retarget(("pool", "apps"))
    names = [name for name, row in rows(form).items() if row["spec"]["presets"]]
    assert names
    values = suggested(form, names[0])
    assert values
    assert form.presetTip(names[0], "@browsers").startswith("Web browsers")
    assert form.presetTip(names[0], "plain-name") == ""
    assert form.presetTip("nonsense", "x") == ""


def test_an_entry_of_devices_tells_what_it_is(out: Form):  # noqa: F811
    summary = out.entrySummary("device", {"device": "speaker", "label": "Desk", "min_volume": 10})
    assert summary["title"] == "Desk"
    # the sound server is read by the window: the line names the output by its description
    assert any("speaker" in line for line in summary["lines"])
    assert out.entrySummary("nonsense", {}) == {"title": "New", "lines": []}


def test_a_list_of_devices_is_written_as_names_or_tables(ui: Ui, out: Form):  # noqa: F811
    document = ui.app.editor.document
    out.setValue("device", [{"device": "speaker"}])
    assert document.get(("channel", "out", "device")) == "speaker"
    out.setValue("device", [{"device": "speaker"}, {"device": "buds"}])
    assert document.get(("channel", "out", "device")) == ["speaker", "buds"]
    out.setValue("device", [{"device": "speaker", "label": "Desk"}])
    assert document.get(("channel", "out", "choices")) == [{"device": "speaker", "label": "Desk"}]
    assert document.get(("channel", "out", "device")) is None
    out.reset("device")
    assert document.get(("channel", "out", "choices")) is None


def test_the_texts_of_a_button_come_from_its_value(out: Form):  # noqa: F811
    loaded = out.buttonLoad("rec", {"press": "mute_others", "led": "muted"})
    assert loaded["texts"]["press"] == "mute_others"
    assert loaded["texts"]["led"] == "muted"
    assert out.buttonLoad("nonsense", None) == {"texts": {}, "kept": {}}
    edited = out.buttonEdit("rec", {"press": "", "led": "muted"}, {})
    assert edited["value"] == "muted"
    assert edited["isNone"] is False
    assert out.buttonEdit("rec", {"press": "", "led": ""}, {})["isNone"] is True
    assert out.buttonEdit("nonsense", {}, {})["value"] is None
    view = out.buttonView("rec", {"press": "", "led": ""}, {})
    assert view["parts"]
    assert out.buttonView("nonsense", {}, {}) == {"parts": [], "meaning": ""}


def test_a_program_start_is_where_its_range_starts(out: Form):  # noqa: F811
    assert out.programStart("min", {"min": 3, "max": 9}) == 3


def test_a_button_without_programs_says_what_each_part_means(out: Form):  # noqa: F811
    logic: Any = out._buttons("rec")  # pyright: ignore[reportPrivateUsage]
    assert isinstance(logic.meaning({"press": "", "led": "muted"}), str)
    assert logic.unknown({"press": "", "led": ""}) == set()


def test_the_context_edits_tables(ui: Ui):
    context = forms_of(ui.app)
    entries = context.tablePut([], 1, "device", "a")
    assert entries == [{}, {"device": "a"}]
    assert context.tableMove(entries, 1, -1) == {"entries": [{"device": "a"}, {}], "index": 0}
    assert context.tableDrop(entries, 0, 2) == {"entries": [{"device": "a"}, {}], "index": 1}
    assert context.tableRemove(entries, 0) == [{"device": "a"}]
    assert context.tableCommitted(entries) == [{"device": "a"}]
    assert context.tableCommitted([{}]) == []
    assert context.programText({"launch": ["mumble"]}) == "launch: mumble"


def test_the_context_describes_and_parses_data(ui: Ui):
    context = forms_of(ui.app)
    assert context.parseData("{ a = 1 }") == {"a": 1}
    assert context.parseData("") is None
    assert context.parseData("nonsense") == "nonsense"
    assert context.dataText({"a": 1}) == "{a = 1}"
    assert context.describe(["a", "b"]) == "a, b"


def test_the_context_chooses_a_file_through_its_dialog(ui: Ui):
    context = forms_of(ui.app)
    context.choose_file = lambda title, current: current + "!"
    assert context.chooseFile("Pick", "/tmp/x") == "/tmp/x!"


def test_the_context_tells_where_things_are_used(ui: Ui):
    context = forms_of(ui.app)
    assert context.usedBy(["slot 1"], "none")["strips"][0]["use"] == "shows"


def test_a_history_is_drawn_in_bars(ui: Ui):
    bars = forms_of(ui.app).historyBars([[time.time() - 3600, True]])
    assert len(bars) == 96


def test_a_new_sound_server_state_reaches_the_forms(ui: Ui, out: Form):  # noqa: F811
    from xtouch_daemon.audio.model import AudioState

    context = forms_of(ui.app)
    revisions: list[int] = []
    context.audioChanged.connect(lambda: revisions.append(context.audioRevision))
    context.set_audio(AudioState())
    assert revisions
    assert context.audio() == AudioState()
    assert suggested(out, "device.device") == []


@pytest.mark.parametrize("name", ["label", "lit_when_idle", "color"])
def test_every_kind_of_row_can_be_set_and_read(ui: Ui, out: Form, name: str):  # noqa: F811
    spec = rows(out)[name]["spec"]
    value: Any = {"text": "Desk", "switch": True, "binding": "red"}[spec["kind"]]
    out.setValue(name, value)
    assert out.valueOf(name) == value
    out.reset(name)
    assert out.valueOf(name) is None or out.valueOf(name) == spec["default"]
