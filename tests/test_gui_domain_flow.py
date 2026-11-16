from typing import Any

import pytest

from xtouch_daemon.config import MAX_STRIPS
from xtouch_daemon.gui.domain.flow import FlowRow, Where, flow_rows, why_not_add
from xtouch_daemon.gui.domain.looks import StripLook, file_state
from xtouch_daemon.live import Snapshot


def snapshot(placement: tuple[int | None, ...] | None) -> Snapshot:
    state = file_state(StripLook("apps", "A", "", "white", True, 0))
    return Snapshot("abc", True, True, None, (state,) * 8, placement=placement)


def apps(collapse: bool = False) -> dict[str, Any]:
    return {"type": "apps", "match": ["brave"], "collapse": collapse}


def test_from_the_file_the_first_eight_places_are_on_the_device() -> None:
    strips = [apps(), apps(collapse=True), *[apps()] * 7]
    rows = flow_rows(strips, None)
    assert [row.text for row in rows] == [*(f"on {n}" for n in range(1, 9)), "waits"]
    # without the daemon nothing collapses
    assert rows[8] == FlowRow(8, Where.WAITS, None)


def test_the_daemon_tells_which_strips_collapsed() -> None:
    strips = [apps(), apps(collapse=True), {"type": "voip", "count": 2}, apps()]
    # places: 0, 1, 2 and 3 for the voip strip, 4, then 5..7 the auto strips that fill the row
    rows = flow_rows(strips, snapshot((0, 3, 4, 5, 6, 7, None, None)))
    assert [(row.where, row.position) for row in rows] == [
        (Where.DEVICE, 0),
        (Where.COLLAPSED, None),
        # one of its places is on the device
        (Where.DEVICE, 1),
        (Where.DEVICE, 2),
        (Where.DEVICE, 3),
        (Where.DEVICE, 4),
        (Where.DEVICE, 5),
    ]
    # a strip without collapse that is not shown waits
    assert flow_rows([apps()] * 9, snapshot((1, 2, 3, 4, 5, 6, 7, 8)))[0].text == "waits"


@pytest.mark.parametrize(
    ("strips", "reason"),
    [
        ([apps()] * 7, None),
        ([apps(collapse=True), *[apps()] * 7], None),
        ([apps(collapse=True), *[apps()] * 8], "8 strips without collapse come first"),
        ([apps()] * 8, "8 strips without collapse come first"),
        ([{"type": "voip", "count": 8}], "8 strips without collapse come first"),
        ([apps(collapse=True)] * MAX_STRIPS, f"at most {MAX_STRIPS} places"),
    ],
)
def test_a_strip_is_added_only_where_it_can_get_a_place(strips: list[dict[str, Any]], reason: str | None) -> None:
    result = why_not_add(strips)
    assert result is None if reason is None else result is not None and reason in result
