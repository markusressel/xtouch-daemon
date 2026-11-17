"""
The slots of a running daemon with channels, states and slots, for the GUI: the mode in a pill next to the preview,
and in its tip which states are on and what each slot shows. Read-only: the GUI edits the old format only (until the
editor knows the new one).
"""

from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.live.messages import SlotsState, SlotView, Snapshot


def slots_status(snapshot: Snapshot | None) -> Status | None:
    """The mode for the pill next to the preview: only while the daemon runs a configuration of slots."""
    if snapshot is None or snapshot.slots is None:
        return None
    slots = snapshot.slots
    if slots.mode_pick is None:
        return Status(f"Mode {slots.mode}", Tone.NEUTRAL, _tip(slots, "The rules pick the mode."))
    return Status(f"Mode {slots.mode} · by hand", Tone.WARN, _tip(slots, "The mode was picked by hand."))


def _tip(slots: SlotsState, how: str) -> str:
    lines = [how, ""]
    for state in slots.states:
        kind = "mode" if state.mode else "state"
        value = "on" if state.value else "off"
        source = f" ({state.source})" if state.source else ""
        override = f", override {state.override}" if state.override != "auto" else ""
        lines.append(f"{kind} {state.name}: {value}{source}{override}")
    lines.append("")
    lines.extend(f"slot {slot.slot}: {_shown(slot)}" for slot in slots.slots)
    for pool, members in slots.waiting.items():
        if members:
            lines.append(f"waiting for {pool}: {', '.join(members)}")
    return "\n".join(lines)


def _shown(slot: SlotView) -> str:
    what = slot.member or slot.channel or "nothing"
    via = f" via {slot.pool}" if slot.pool is not None and slot.member is not None else ""
    return f"{what}{via}"
