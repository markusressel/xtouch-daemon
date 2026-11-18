"""
Why a slot shows what it shows, and why a channel is where it is, from the resolver's trace in the live view: the
why line of the GUI and `xtouch-daemon why`.
"""

from xtouch_daemon.live.messages import SlotsState, SlotView
from xtouch_daemon.slots.model import APPS, AUTO, DEVICES, PEOPLE


def why_slot(slots: SlotsState, slot: int) -> str:
    """`Slot 2: browser if call: doesn't hold (call is off); shows auto:app:firefox`."""
    view = _view(slots, slot)
    if view is None:
        return f"Slot {slot}: the daemon tells nothing about it"
    return f"Slot {slot}: " + "; ".join(view.why)


_NONE_OF = {APPS: "no application", PEOPLE: "nobody", DEVICES: "no device", AUTO: "no person or application"}
"""What a pool with no member on a slot has there, by pool."""


def why_channel(slots: SlotsState, name: str) -> str:
    """
    `browser: on slot 2; not slot 8 (on slot 2 (tie, to the left))`: the slots that show a channel and why not the
    others. For a pool its members and who waits: `people: Alice on 6, Bob on 5; waiting: Carol`.
    """
    return f"{name}: {where(slots, name)}"


def where(slots: SlotsState, name: str) -> str:
    """
    `why_channel` without the name: `on slot 2; not slot 8 (...)`, `Alice on 6; waiting: Carol`, `no application on
    a slot`.
    """
    if any(view.pool == name and view.channel != name for view in slots.slots) or name in slots.waiting:
        seated = [f"{_member(view.member)} on {view.slot}" for view in slots.slots if view.pool == name and view.member]
        waiting = slots.waiting.get(name, ())
        parts = [", ".join(seated) if seated else f"{_NONE_OF.get(name, 'nothing')} on a slot"]
        parts += [f"waiting: {', '.join(_member(member) for member in waiting)}"] if waiting else []
        return "; ".join(parts)
    parts = [f"on slot {view.slot}" for view in slots.slots if name in (view.channel, view.member)]
    for view in slots.slots:
        if name in (view.channel, view.member):
            continue
        reasons = [_reason(line, name) for line in view.why]
        parts.extend(f"not slot {view.slot} ({reason})" for reason in reasons if reason is not None)
    return "; ".join(parts) if parts else "on no slot, and no slot asks for it"


def _member(member: str) -> str:
    """A member of a pool by its name: `app:Spotify` is `Spotify`, `person:Alice` `Alice`."""
    kind, _, named = member.partition(":")
    return named if kind in ("app", "person", "device") and named else member


def why(slots: SlotsState, target: str) -> str:
    """For a slot (its number), a channel or a pool (its id)."""
    return why_slot(slots, int(target)) if target.isdigit() else why_channel(slots, target)


def _view(slots: SlotsState, slot: int) -> SlotView | None:
    return next((view for view in slots.slots if view.slot == slot), None)


def _reason(line: str, name: str) -> str | None:
    """The reason of a line of the trace about the channel (`browser if call: doesn't hold (...)`), else None."""
    subject, separator, reason = line.partition(": ")
    if not separator or subject.partition(" if ")[0] != name:
        return None
    return reason
