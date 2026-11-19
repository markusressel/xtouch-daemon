"""Entries as TOML text for the clipboard, and back."""

from xtouch_daemon.gui.domain.clipboard import (
    candidates_text,
    parse_candidates,
    parse_tables,
    pasted_id,
    tables_text,
)
from xtouch_daemon.gui.domain.slot_stacks import Row


def test_tables_are_text_as_in_the_file_and_back():
    tables = {"channel": {"mic": {"type": "input", "select": {"press": "mute"}}}}
    text = tables_text(tables)
    assert text == '[channel.mic]\ntype = "input"\nselect = {press = "mute"}\n'
    assert parse_tables(text, ("channel", "pool")) == tables
    # other sections, and what is no TOML, have none
    assert parse_tables(text, ("state",)) == {}
    assert parse_tables("not = = toml", ("channel",)) == {}


def test_a_pasted_id_is_one_after_its_own():
    assert pasted_id({"out"}, "mic") == "mic"
    assert pasted_id({"mic"}, "mic") == "mic_2"
    assert pasted_id({"mic", "mic_2"}, "mic_2") == "mic_3"


def test_candidates_are_values_of_the_list_of_a_slot():
    candidates = [Row("browser", "call"), Row("mic", options={"color": "red"})]
    text = candidates_text(candidates)
    assert text == '"browser if call",\n{show = "mic", color = "red"}'
    assert parse_candidates(text) == candidates
    # or slots as in the file
    assert parse_candidates('[slots]\n3 = ["out", "auto"]') == [Row("out"), Row("auto")]
    assert parse_candidates('3 = "out"') == [Row("out")]
    assert parse_candidates("[channel.mic]\ntype = 1") == []
    assert parse_candidates("not = = toml") == []
