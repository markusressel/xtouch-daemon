"""Helpers of the tests of the page Slots in Qt Quick: what the daemon tells, and reading the cards as text."""

from typing import Any

from PyQt6.QtCore import QObject

from tests.support.quick import Ui
from xtouch_daemon.gui.quick.pages.slots import Live, SlotsPage
from xtouch_daemon.live.messages import SlotsState, SlotView, Snapshot, StateView


def page(ui: Ui) -> SlotsPage:
    slots = ui.app.slots
    assert isinstance(slots, SlotsPage)
    return slots


def snapshot(candidates: tuple[int | None, ...], pick: str | None = None, call: bool = True) -> Snapshot:
    """What the daemon tells: the candidate each slot shows, and the states."""
    views = tuple(
        SlotView(slot, candidate, None, None, None, (f"shows {candidate}",))
        for slot, candidate in enumerate(candidates, 1)
    )
    states = (
        StateView("call", call, False, None, "mumble runs" if call else None, "auto"),
        StateView("gaming", pick == "gaming", True, None, None, "auto"),
    )
    slots = SlotsState("default", pick, views, states, {})
    return Snapshot("x", True, sound_server=True, mqtt=None, strips=(), slots=slots)


def tell(ui: Ui, shown: Snapshot | None, **live: Any) -> Live:
    """The daemon tells `shown`: the page reads it, and `live` changes what else the page reaches."""
    slots = page(ui)
    slots.live = Live(snapshot=lambda: shown, **live)
    slots.show_live(shown)
    ui.settle()
    return slots.live


def model_rows(model: QObject) -> list[dict[str, Any]]:
    """The rows of a `KeyedListModel`."""
    return [dict(values) for _, values in model.rows]  # pyright: ignore[reportAttributeAccessIssue]


def texts(ui: Ui, slot: int) -> list[str]:
    """What each row of a card reads: ▶ on the one the device shows, its number, its condition, what it shows."""
    found: list[str] = []
    for row in model_rows(page(ui).cards[slot - 1].rows):
        if row["end"] or not row["candidate"]:
            found.append(row["show"])
            continue
        parts = [
            row["number"],
            row["lead"],
            *(f"{'or ' if chip.get('or') else ''}{chip['text']}" for chip in row["chips"]),
        ]
        text = " ".join(part for part in parts if part) + f" → {row['show']}"
        found.append(f"▶ {text}" if row["state"] == "shown" else text)
    return found


def click_row(ui: Ui, slot: int, row: int) -> None:
    press(ui, f"row_{slot}_{row}")


def polish(ui: Ui) -> None:
    """Lets the window lay out what changed (it does so when it draws), so items are where a click finds them."""
    ui.grab()
    ui.settle()


def press(ui: Ui, target: str, **kwargs: Any) -> None:
    """Clicks an item once the window has laid out what changed."""
    polish(ui)
    ui.click(target, **kwargs)
