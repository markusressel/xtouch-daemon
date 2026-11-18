"""
Where the window shows a problem.
"""

from xtouch_daemon.config.files import Problem
from xtouch_daemon.gui.domain.problems import Place, place_of


def place(path: tuple[int | str, ...], message: str = "wrong") -> Place | None:
    return place_of(Problem(path, message, "invalid"))


def test_problems_are_shown_where_their_part_is_edited():
    assert place(("channel", "out", "volume")) == Place("channels", channel=("channel", "out"))
    assert place(("pool", "auto", "hold")) == Place("channels", channel=("pool", "auto"))
    assert place(("people", "order")) == Place("channels", channel=("pool", "people"))
    assert place(("state", "call", "delay_on")) == Place("states", state="call")
    assert place(("slots", "2", 0)) == Place("slots", slot=2)
    assert place(("controls", "9")) == Place("slots")
    assert place(("aliases", "x")) == Place("aliases")
    assert place(("device", "name")) == Place("device")


def test_problems_of_the_whole_file_go_to_the_section_they_name():
    assert place((), "channels of Home Assistant need an [mqtt] section") == Place("mqtt")
    assert place((), "something else") is None
