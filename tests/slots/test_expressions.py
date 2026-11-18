"""
The conditions: their grammar, their values, and the errors that say where.
"""

import pytest

from xtouch_daemon.slots.expressions import And, ExpressionError, Name, Not, Or, Present, parse


def test_and_binds_tighter_than_or_and_not_tighter_than_both():
    condition = parse("a or b and not c")
    assert condition.expr == Or((Name("a", 0), And((Name("b", 5), Not(Name("c", 15))))))
    assert condition.holds({"a": False, "b": True, "c": False}, lambda target: False)
    assert not condition.holds({"a": False, "b": True, "c": True}, lambda target: False)
    assert parse("(a or b) and c").holds({"a": True, "b": False, "c": False}, lambda target: False) is False


def test_present_asks_about_the_candidate_or_a_named_one():
    condition = parse("gaming and present or present(buds)")
    asked: list[str | None] = []

    def present(target: str | None) -> bool:
        asked.append(target)
        return target == "buds"

    assert condition.holds({"gaming": True}, present)
    assert asked == [None, "buds"]
    assert condition.states == {"gaming"}
    assert condition.presence == {None, "buds"}
    assert condition.explain({"gaming": True}, present) == "gaming is on, present: no, present(buds): yes"


@pytest.mark.parametrize(
    ("text", "position", "message"),
    [
        ("", 0, "empty condition"),
        ("call and", 8, "the condition ends too early"),
        ("(call", 5, "the condition ends too early"),
        ("(call gaming", 6, "expected ')', not 'gaming'"),
        ("call)", 4, "unexpected ')'"),
        ("call gaming", 5, "unexpected 'gaming'"),
        ("Call", 0, "unexpected 'C'"),
        ("call  & gaming", 6, "unexpected '&'"),
        ("and", 0, "unexpected 'and'"),
        ("present(and)", 8, "present(...) takes a channel or pool"),
        ("present()", 8, "present(...) takes a channel or pool"),
    ],
)
def test_errors_say_where(text: str, position: int, message: str):
    with pytest.raises(ExpressionError) as error:
        parse(text)
    assert (error.value.position, error.value.message) == (position, message)
    assert error.value.caret() == f"{text}\n{' ' * position}^ {message}"


def test_spaces_around_are_fine():
    assert parse("  call  ").expr == Name("call", 2)
    assert parse("present").expr == Present(None, 0)
