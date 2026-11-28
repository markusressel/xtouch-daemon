"""The logic behind the fields: lists of tables, buttons, bindings, used-by and history bars, in words and as data."""

from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.gui.quick.test_forms import out, rows  # noqa: F401  (the fixture)
from xtouch_daemon.gui.quick.forms import tables
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.forms.usage import history_bars, used_by

# -- lists of tables ------------------------------------------------------------------------------------------------


def test_put_adds_entries_up_to_the_index_and_removes_a_none():
    entries = tables.put([], 1, "device", "speaker")
    assert entries == [{}, {"device": "speaker"}]
    assert tables.put(entries, 1, "device", None) == [{}, {}]


def test_an_entry_moves_but_not_past_the_ends():
    entries = [{"device": "a"}, {"device": "b"}, {"device": "c"}]
    assert tables.move(entries, 0, 1) == ([{"device": "b"}, {"device": "a"}, {"device": "c"}], 1)
    assert tables.move(entries, 0, -1) == (entries, 0)
    assert tables.move(entries, 2, 5) == (entries, 2)
    assert tables.move([], 0, 1) == ([], 0)


def test_an_entry_dropped_before_another_lands_there():
    entries = [{"device": "a"}, {"device": "b"}, {"device": "c"}]
    assert tables.move_before(entries, 0, 3) == ([{"device": "b"}, {"device": "c"}, {"device": "a"}], 2)
    assert tables.move_before(entries, 2, 0) == ([{"device": "c"}, {"device": "a"}, {"device": "b"}], 0)
    assert tables.move_before(entries, 9, 0) == (entries, 9)


def test_removing_and_committing_entries():
    entries = [{"device": "a"}, {}, {"device": "c"}]
    assert tables.remove(entries, 0) == [{}, {"device": "c"}]
    assert tables.committed(entries) == [{"device": "a"}, {"device": "c"}]
    assert tables.committed([{}]) is None


def test_devices_are_written_as_names_while_they_have_nothing_else():
    assert tables.written([{"device": "a"}]) == ("a", None)
    assert tables.written([{"device": "a"}, {"device": "b"}]) == (["a", "b"], None)
    assert tables.written([{"device": "a", "label": "A"}]) == (None, [{"device": "a", "label": "A"}])
    assert tables.written([{}]) == (None, None)


def test_devices_are_read_from_names_or_tables():
    assert tables.entries_of("a", None) == [{"device": "a"}]
    assert tables.entries_of(["a", "b"], None) == [{"device": "a"}, {"device": "b"}]
    assert tables.entries_of("x", [{"device": "y", "label": "Y"}]) == [{"device": "y", "label": "Y"}]
    assert tables.entries_of(None, None) == []


def test_an_entry_says_what_it_is():
    title, lines = tables.summary(
        {"device": "speaker", "label": "Desk", "min_volume": 10, "max_volume": 80}, lambda *_: ""
    )
    assert title == "Desk"
    assert lines == ["speaker", "Volume 10 – 80 %"]
    assert tables.summary({}, lambda *_: "") == ("New", [])
    assert tables.summary({"device": "d", "profile": "hdmi"}, lambda *_: "")[1] == [
        'Switches its sound card to "hdmi" first'
    ]
    assert tables.summary({"device": "d", "max_volume": 50}, lambda *_: "")[1] == ["Volume up to 50 %"]
    assert tables.summary({"device": "d", "min_volume": 5}, lambda *_: "")[1] == ["Volume from 5 %"]


def test_a_description_loses_what_the_sound_server_adds():
    assert tables.trim("Analog Stereo Output (active)") == "Analog Stereo Output"
    assert tables.trim("HDMI, 5.1") == "HDMI"


# -- used by and history --------------------------------------------------------------------------------------------


def test_used_by_marks_strips_and_names_the_rest():
    result = used_by(["slot 2", "controls 5", "pool games"], "Nothing uses it")
    uses = {strip["slot"]: strip["use"] for strip in result["strips"]}
    assert uses[2] == "shows"
    assert uses[5] == "controls"
    assert uses[1] == "none"
    assert result["rest"] == "pool games"
    assert result["anyStrip"] is True


def test_used_by_nothing_says_so():
    result = used_by([], "Nothing uses it")
    assert result["rest"] == "Nothing uses it"
    assert result["title"] is False
    assert result["anyStrip"] is False


def test_history_bars_cover_the_last_day():
    now = datetime(2025, 1, 2, 12, 0).timestamp()
    on = now - timedelta(hours=3).total_seconds()
    bars = history_bars([(on, True)], now)
    assert len(bars) == 96
    assert any(bar["on"] > 0 for bar in bars)
    assert any(bar["label"] for bar in bars)
    assert all(0 <= bar["on"] <= 1 for bar in bars)


# -- buttons and bindings, through a form ---------------------------------------------------------------------------


def test_a_button_alone_with_its_led_is_the_short_form(out: Form):  # noqa: F811
    logic: Any = out._buttons("rec")  # pyright: ignore[reportPrivateUsage]
    assert logic is not None
    assert logic.value({"press": "", "led": "muted"}, {}) == "muted"
    assert logic.value({"press": "mute_others", "led": "muted"}, {}) == {"press": "mute_others", "led": "muted"}
    assert logic.value({}, {}) is None


def test_a_program_typed_in_a_button_becomes_a_table(out: Form):  # noqa: F811
    logic: Any = out._buttons("rec")  # pyright: ignore[reportPrivateUsage]
    value = logic.value({"press": "run: notify-send hi there", "led": ""}, {})
    assert value == {"press": {"run": ["notify-send", "hi", "there"]}}
    texts, kept = logic.load(value)
    assert texts["press"] == "run: notify-send hi there"
    assert "press" in kept


def test_a_service_keeps_its_other_options_when_its_name_changes(out: Form):  # noqa: F811
    logic: Any = out._buttons("rec")
    kept = {"press": {"service": "light.toggle", "entity": "light.desk"}}
    value = logic.value({"press": "service: light.turn_on", "led": ""}, kept)
    assert value == {"press": {"service": "light.turn_on", "entity": "light.desk"}}


def test_the_parts_of_a_button_have_items_and_meanings(out: Form):  # noqa: F811
    logic: Any = out._buttons("rec")
    view = logic.view({"press": "", "led": ""}, {})
    assert [part["name"] for part in view["parts"]] == [column.name for column in logic.columns]
    press = view["parts"][0]
    assert press["items"]
    assert press["placeholder"].startswith("default")


@pytest.mark.parametrize("text", ["run: a b", "launch: a", "watch: a", "poll: a"])
def test_every_program_kind_is_recognised(text: str):
    from xtouch_daemon.gui.quick.forms.buttons import program_table

    table = program_table(text)
    assert table is not None
    assert next(iter(table)) == text.split(":")[0]


def test_other_texts_are_no_programs():
    from xtouch_daemon.gui.quick.forms.buttons import program_table

    assert program_table("muted") is None
    assert program_table("nonsense: x") is None
    assert program_table('run: a "b') == {"run": ["a", '"b']}
