"""The forms made from the models: the rows of a channel, values in place, reset, retargeting and problems."""

from typing import Any

import pytest
from PyQt6.QtCore import QModelIndex

from tests.support.quick import Ui
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.forms.strips import channel_form, pool_form


def rows(form: Form) -> dict[str, dict[str, Any]]:
    """The rows of a form by option name: their `spec` and their `info`."""
    model: Any = form.rows
    return {spec["name"]: {"spec": spec, "info": info} for _key, spec, info in model.rows}


@pytest.fixture
def out(ui: Ui) -> Form:
    form = channel_form(forms_of(ui.app), "output")
    form.retarget(("channel", "out"))
    form.active = True
    return form


def test_a_form_has_a_row_per_option(out: Form):
    names = list(rows(out))
    assert "device" in names
    assert rows(out)["label"]["spec"]["kind"] == "text"
    assert rows(out)["lit_when_idle"]["spec"]["kind"] == "switch"
    assert rows(out)["color"]["spec"]["kind"] == "binding"


def test_a_value_shows_in_place_without_new_rows(ui: Ui, out: Form):
    model: Any = out.rows
    inserted: list[int] = []
    model.rowsInserted.connect(lambda *_: inserted.append(1))
    model.rowsRemoved.connect(lambda *_: inserted.append(1))
    out.setValue("absent_after", 1.5)
    assert ui.app.editor.document.get(("channel", "out", "absent_after")) == 1.5
    assert rows(out)["absent_after"]["info"]["value"] == 1.5
    assert inserted == []


def test_loading_does_not_write_back(ui: Ui, out: Form):
    before = ui.app.editor.history.can_undo if hasattr(ui.app.editor.history, "can_undo") else None
    out.refresh()
    out.retarget(("channel", "out"))
    assert ui.app.editor.document.get(("channel", "out", "absent_after")) is None
    if before is not None:
        assert ui.app.editor.history.can_undo == before


def test_a_reset_unsets_the_option(ui: Ui, out: Form):
    out.setValue("absent_after", 1.5)
    assert rows(out)["absent_after"]["info"]["set"] is True
    out.reset("absent_after")
    assert ui.app.editor.document.get(("channel", "out", "absent_after")) is None
    assert rows(out)["absent_after"]["info"]["set"] is False


def test_a_form_retargets_to_another_channel(ui: Ui, out: Form):
    ui.app.editor.add_channel("output", {"absent_after": 7})
    other = [name for name in ui.app.editor.document.get(("channel",)) if name != "out"][-1]
    out.retarget(("channel", other))
    assert rows(out)["absent_after"]["info"]["value"] == 7
    assert list(out.basePath) == ["channel", other]


def test_an_inactive_form_waits_with_its_changes(ui: Ui, out: Form):
    out.active = False
    ui.app.editor.document.set(("channel", "out", "absent_after"), 9)
    ui.app.editor.edited()
    assert rows(out)["absent_after"]["info"]["value"] != 9
    out.active = True
    assert rows(out)["absent_after"]["info"]["value"] == 9


def test_a_problem_shows_on_its_row(ui: Ui, out: Form):
    ui.app.editor.document.set(("channel", "out", "absent_after"), "soon")
    ui.app.editor.edited()
    assert rows(out)["absent_after"]["info"]["problems"]


def test_the_titles_share_a_column(out: Form):
    assert out.titleWidth > 0


def test_a_pool_has_its_own_options(ui: Ui):
    form = pool_form(forms_of(ui.app), "apps")
    form.retarget(("pool", "apps"))
    assert "hold" in rows(form)


def test_the_model_counts_its_rows(out: Form):
    model: Any = out.rows
    assert model.count == len(rows(out))
    assert model.rowCount(QModelIndex()) == model.count
    assert model.rowCount(model.index(0)) == 0


def test_help_is_rich_text_with_the_default(ui: Ui):
    text = forms_of(ui.app).help("Seconds the `fader` waits.", "dark", "https://example.org", "3")
    assert "DEFAULT" in text
    assert "https://example.org" in text
    assert "<code" in text
