"""
Two small pictures of the forms of a channel and a state, as data for QML: where it is used (`UsedBy`: the eight
strips with the slots that show it or whose controls use it, and the rest in words) and the last day of a state
(`HistoryBars`:
a bar per quarter of an hour).
"""

import re
from collections.abc import Sequence
from typing import Any

from xtouch_daemon.gui.domain.states import spans_on

STRIPS = 8
LABEL_EVERY = 6
"""A label of the clock under every sixth hour."""


def used_by(where: Sequence[str], none: str) -> dict[str, Any]:
    """
    `where` as `uses` and `state_uses` tell it (`slot 2`, `controls 5`, `pool games`, `state call`): the strips, each
    `shows` (a slot shows it), `controls` (only the controls of a slot use it) or `none`, with the tip of each; the
    rest in words, or `none` while nothing uses it.
    """
    slots = {int(found[1]) for found in (re.fullmatch(r"slot (\d+)", entry) for entry in where) if found}
    controls = {int(found[1]) for found in (re.fullmatch(r"controls (\d+)", entry) for entry in where) if found}
    rest = [entry for entry in where if not re.fullmatch(r"(slot|controls) \d+", entry)]
    strips: list[dict[str, Any]] = []
    for number in range(1, STRIPS + 1):
        shows, uses = number in slots, number in controls
        strips.append(
            {
                "slot": number,
                "use": "shows" if shows else "controls" if uses else "none",
                "tip": f"Slot {number} shows it. Click to show the slot."
                if shows
                else f"The controls of slot {number} use it. Click to show the slot."
                if uses
                else "",
            }
        )
    return {
        "title": bool(where),
        "strips": strips,
        "anyStrip": bool(slots | controls),
        "rest": ", ".join(rest) if where else none,
    }


def history_bars(history: Sequence[tuple[float, bool]], now: float) -> list[dict[str, Any]]:
    """
    The bars of the last day of a state: per quarter of an hour how much of it was on and how much the daemon
    watched (both as shares of the quarter), its tip, and the label of the clock under it, if it has one.
    """
    spans = spans_on(history, now)
    bars: list[dict[str, Any]] = []
    for index, span in enumerate(spans):
        label = (
            f"{span.start:%H}:00"
            if index < len(spans) - 12 and span.start.hour % LABEL_EVERY == 0 and span.start.minute == 0
            else ""
        )
        bars.append(
            {
                "known": min(1.0, span.known / span.length) if span.known else 0.0,
                "on": min(1.0, span.on / span.length),
                "watched": bool(span.known),
                "tip": span.describe(),
                "label": label,
            }
        )
    return bars
