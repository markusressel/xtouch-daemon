"""
`simulate`: the slots of a configuration in given states, and the table of its outcomes.
"""

from pathlib import Path

from tests.support.cli import invoke
from tests.support.slots import EXAMPLE


def test_the_slots_and_why():
    result = invoke(
        "simulate", str(EXAMPLE), "--state", "call", "--playing", "mpv", "--playing", "spotify", "--absent", "mic"
    )
    assert result.exit_code == 0
    assert result.output.splitlines()[:6] == [
        "1  out",
        "     game if gaming: doesn't hold (gaming is off)",
        "2  browser",
        "     people if gaming and present: doesn't hold (gaming is off, present: no)",
        "3  auto:mpv",
        "4  auto:spotify",
    ]
    # an absent channel keeps its place
    assert "8  mic" in result.output


def test_who_waits():
    result = invoke("simulate", str(EXAMPLE), *(arg for app in "abcdefg" for arg in ("--playing", app)))
    assert result.output.splitlines()[-1] == "waiting for a slot of auto: g"
    result = invoke("simulate", str(EXAMPLE), "--mode", "gaming", "--person", "Bob", "--person", "Al")
    assert "2  people:Bob" in result.output
    assert result.output.splitlines()[-1] == "waiting for a slot of people: Al"


def test_the_table():
    result = invoke("simulate", str(EXAMPLE), "--table")
    assert result.output.splitlines()[0].split() == ["when", "1", "2", "3-6", "7", "8"]


def test_problems(tmp_path: Path):
    result = invoke("simulate", str(EXAMPLE), "--state", "cal")
    assert result.exit_code == 1
    assert "cal is no mode, state or channel" in result.output
    broken = tmp_path / "broken.toml"
    broken.write_text('[slots]\n1 = "nothing"\n')
    result = invoke("simulate", str(broken))
    assert result.exit_code == 1
    assert "slots.1[0]: nothing is no channel or pool" in result.output
