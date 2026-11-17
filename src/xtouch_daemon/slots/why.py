"""
Why a slot shows what it shows, and why a channel is where it is, from the resolver's trace in the live view: the
why line of the GUI and `xtouch-daemon why`.
"""

from xtouch_daemon.live.messages import SlotsState, SlotView


def why_slot(slots: SlotsState, slot: int) -> str:
    """`Slot 2: browser if call: doesn't hold (call is off); shows auto:app:firefox`."""
    view = _view(slots, slot)
    if view is None:
        return f"Slot {slot}: the daemon tells nothing about it"
    return f"Slot {slot}: " + "; ".join(view.why)


def why_channel(slots: SlotsState, name: str) -> str:
    """`browser: on 2; not 8 (on slot 2 (tie, to the left))`: the slots that show it and why not the others."""
    parts = [f"on {view.slot}" for view in slots.slots if name in (view.channel, view.member)]
    for view in slots.slots:
        if name in (view.channel, view.member):
            continue
        reasons = [_reason(line, name) for line in view.why]
        parts.extend(f"not {view.slot} ({reason})" for reason in reasons if reason is not None)
    return f"{name}: " + ("; ".join(parts) if parts else "on no slot, and no slot asks for it")


def why(slots: SlotsState, target: str) -> str:
    """For a slot (its number) or a channel (its id)."""
    return why_slot(slots, int(target)) if target.isdigit() else why_channel(slots, target)


def _view(slots: SlotsState, slot: int) -> SlotView | None:
    return next((view for view in slots.slots if view.slot == slot), None)


def _reason(line: str, name: str) -> str | None:
    """The reason of a line of the trace about the channel (`browser if call: doesn't hold (...)`), else None."""
    subject, separator, reason = line.partition(": ")
    if not separator or subject.partition(" if ")[0] != name:
        return None
    return reason
