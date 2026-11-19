"""
What the sound server has right now (and what else is known of it), as suggestions for the options that name devices
and applications; which of them a value matches, and where.
"""

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from xtouch_daemon.audio.model import AudioState, Card, Direction
from xtouch_daemon.config import presets
from xtouch_daemon.live.messages import KnownDevice


@dataclass(frozen=True)
class Suggestion:
    value: str
    """What goes into the option."""
    detail: str
    """What it is, for people."""
    tip: str = ""
    """More about it, e.g. what a preset stands for."""
    origin: str = ""
    """Where it is known from, e.g. "default", "active", "profile Digital Stereo", "seen 3 days ago"; "" for now."""
    names: tuple[str, ...] = ()
    """Other names it goes by, which a value may name it with too (a device: its description)."""
    card: str | None = None
    """For a device that is there only in another profile of its card: the card..."""
    profile: str | None = None
    """...and that profile."""
    present: bool = True
    """Whether it is there right now."""
    forget: Callable[[], None] | None = field(default=None, compare=False)
    """Forgets it, for a device only remembered (see `KnownDevice`)."""

    @property
    def preset(self) -> bool:
        """Whether it is a preset (`@browsers`) rather than a name."""
        return presets.is_preset(self.value)


def preset_tip(value: str, kind: presets.Kind) -> str:
    """
    What a preset in a list of the kind stands for, e.g. "Web browsers: firefox, librewolf, ...", or that it can't be
    used there; "" for a plain name or an unknown preset.
    """
    preset = presets.preset_of(value)
    if preset is None:
        return ""
    names = preset.names(kind)
    if names is None:
        return f"{preset.description}: not for {presets.WHERE[kind]}"
    return f"{preset.description}: {', '.join(names)}" + (f"\n\n{preset.note}" if preset.note else "")


def preset_suggestions(kind: presets.Kind) -> tuple[Suggestion, ...]:
    """The presets that can be used in a list of the kind, with what they stand for as the tip."""
    return tuple(
        Suggestion(preset.entry, preset.description, preset_tip(preset.entry, kind), origin="preset")
        for preset in presets.PRESETS.values()
        if kind in preset.kinds
    )


def _count(number: int, thing: str) -> str:
    return f"{number} {thing}{'' if number == 1 else 's'}"


def summary(state: AudioState) -> str:
    """What the sound server has, e.g. "2 outputs, 1 input, 3 applications"."""
    applications = len({stream.app for stream in state.streams})
    return ", ".join(
        (_count(len(state.outputs), "output"), _count(len(state.inputs), "input"), _count(applications, "application"))
    )


def contents(state: AudioState) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """
    What the sound server has, by kind (outputs, inputs, applications that play): a name each and a note on it,
    "(the default)" for the default device, "" otherwise.
    """

    def named(direction: Direction) -> tuple[tuple[str, str], ...]:
        return tuple(
            (device.description, "(the default)" if state.is_default(device) else "")
            for device in state.devices(direction)
        )

    applications = tuple((app, "") for app in sorted({stream.app for stream in state.streams}, key=str.casefold))
    return (("Outputs", named(Direction.OUTPUT)), ("Inputs", named(Direction.INPUT)), ("Applications", applications))


def devices(
    state: AudioState,
    direction: Direction,
    known: tuple[KnownDevice, ...] = (),
    now: float = 0.0,
    forget: Callable[[KnownDevice], None] | None = None,
) -> tuple[Suggestion, ...]:
    """
    The devices for `device`, by node name, as `xtouch-daemon list-devices` lists them; then those that the other
    profiles of their cards would make (see `profile_devices`), and those the daemon remembers (`known`, see
    `remembered`; `now` in seconds since the epoch, `forget` forgets one).
    """
    there = _devices_there(state, direction)
    others = profile_devices(state, direction, {suggestion.value for suggestion in there})
    return there + remembered(state, direction, others, known, now, forget)


def remembered(
    state: AudioState,
    direction: Direction,
    others: tuple[Suggestion, ...],
    known: tuple[KnownDevice, ...],
    now: float,
    forget: Callable[[KnownDevice], None] | None,
) -> tuple[Suggestion, ...]:
    """
    `others` (devices that are not there) with what the daemon remembers of them, and the devices it remembers that
    are not there and not among them. A remembered device of a card that is there in another profile than the one
    that made it needs that profile: picked for a choice, it fills in the card and the profile.
    """
    there = {device.name for device in state.devices(direction)}
    found = {suggestion.value: suggestion for suggestion in others}
    for device in known:
        if device.direction != direction.value or device.name in there:
            continue
        card = state.card(device.card)
        switch = card is not None and device.profile is not None and card.profile != device.profile
        before = found.get(device.name)
        suggestion = Suggestion(
            device.name,
            device.description,
            origin=f"seen {ago(now - device.seen)}",
            names=(device.description,),
            card=device.card if switch else None,
            profile=device.profile if switch else None,
            present=False,
            forget=None if forget is None else lambda device=device: forget(device),
        )
        if before is not None:
            # the profile it needs is known either way; the description is the real one
            suggestion = replace(
                before,
                detail=device.description,
                names=(device.description,),
                origin=f"{suggestion.origin}, {before.origin}",
                forget=suggestion.forget,
            )
        found[device.name] = suggestion
    return tuple(found.values())


def ago(seconds: float) -> str:
    """How long ago, in words: "today", "yesterday", "3 days ago"."""
    days = int(max(seconds, 0.0) // 86400)
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


def _devices_there(state: AudioState, direction: Direction) -> tuple[Suggestion, ...]:
    return tuple(
        Suggestion(
            device.name,
            device.description,
            origin="default" if state.is_default(device) else "",
            names=(device.description,),
        )
        for device in state.devices(direction)
    )


def profile_devices(state: AudioState, direction: Direction, there: set[str]) -> tuple[Suggestion, ...]:
    """
    The devices of the direction that a profile of an ALSA card makes that is not active: PipeWire names them from
    the card and the part of the profile, e.g. `alsa_card.pci-0000_11_00.4` with `output:iec958-stereo` makes
    `alsa_output.pci-0000_11_00.4.iec958-stereo`. Cards with other names (UCM, pro audio) name them otherwise: none.
    """
    found: dict[str, Suggestion] = {}
    for card in state.cards:
        if not card.name.startswith(ALSA_CARD):
            continue
        for profile in card.profiles:
            if profile.name == card.profile:
                continue
            for part, description in _profile_parts(profile.name, profile.description):
                kind, _, which = part.partition(":")
                name = f"alsa_{kind}.{card.name.removeprefix(ALSA_CARD)}.{which}"
                if kind != direction.value or not which or name in there or name in found:
                    continue
                found[name] = Suggestion(
                    name,
                    _card_part(card, description),
                    origin="after a switch of the profile",
                    card=card.name,
                    profile=profile.name,
                    present=False,
                )
    return tuple(found.values())


ALSA_CARD = "alsa_card."


def _profile_parts(name: str, description: str) -> list[tuple[str, str]]:
    """The parts of a profile (`output:x+input:y`) with their descriptions, where the description has them too."""
    parts = name.split("+")
    descriptions = description.split(" + ")
    return list(
        zip(parts, descriptions if len(descriptions) == len(parts) else [description] * len(parts), strict=True)
    )


def _card_part(card: Card, description: str) -> str:
    return f"{description} ({card.description})" if card.description else description


def applications(state: AudioState) -> tuple[Suggestion, ...]:
    """The names of the applications that play, for `[aliases]`."""
    names = dict.fromkeys(stream.app for stream in state.streams)
    return tuple(
        Suggestion(name, ", ".join(sorted({stream.binary for stream in state.streams_of_app(name) if stream.binary})))
        for name in names
    )


def patterns(state: AudioState) -> tuple[Suggestion, ...]:
    """Parts of names and binaries that match the applications that play, for `match` and `ignore`."""
    found: dict[str, str] = {}
    for stream in state.streams:
        if stream.binary:
            found.setdefault(stream.binary, f"the binary of {stream.app}")
        found.setdefault(stream.app, "an application")
    return tuple(Suggestion(value, detail) for value, detail in found.items())


def profiles(state: AudioState, direction: Direction) -> tuple[Suggestion, ...]:
    """The profiles of the sound cards with devices of the direction, by name, for `profiles`."""
    cards = {device.card for device in state.devices(direction)}
    return tuple(
        Suggestion(
            profile.name,
            profile.description,
            origin="active" if profile.name == card.profile else "",
            names=(profile.description,),
        )
        for card in state.cards
        if card.name in cards
        for profile in card.profiles
    )


def cards(state: AudioState) -> tuple[Suggestion, ...]:
    """
    The sound cards by name, for `card` of `choices`: by their description, or else by the devices they have now (as
    `list-devices` has them), whose names are the tip.
    """

    def of(card: Card) -> tuple[str, ...]:
        return tuple(device.description for device in (*state.outputs, *state.inputs) if device.card == card.name)

    return tuple(
        Suggestion(
            card.name,
            card.description or (f"The card of {', '.join(of(card))}" if of(card) else ""),
            tip=", ".join(device.name for device in (*state.outputs, *state.inputs) if device.card == card.name),
            names=(card.description,) if card.description else (),
        )
        for card in state.cards
    )


def card_profiles(state: AudioState, card: str | None) -> tuple[Suggestion, ...]:
    """The profiles of the card of `card` (its name or description, wildcards allowed), for `profile` of `choices`."""
    found = state.card_matching(card) if card else None
    if found is None:
        return ()
    return tuple(
        Suggestion(
            profile.name,
            profile.description,
            origin="active" if profile.name == found.profile else "",
            names=(profile.description,),
        )
        for profile in found.profiles
    )


# -- matching ------------------------------------------------------------------------------------------------------


def is_pattern(text: str) -> bool:
    """Whether a value has wildcards (`*`, `?`), as the daemon matches them."""
    return "*" in text or "?" in text


def names_of(suggestion: Suggestion) -> tuple[str, ...]:
    return (suggestion.value, *suggestion.names)


def known_matches(value: str, suggestions: tuple[Suggestion, ...]) -> tuple[Suggestion, ...]:
    """
    What a value of an option names, as the daemon matches it: by any of its names, whole (a name or a description),
    or with wildcards (`bluez_output.*`).
    """
    if is_pattern(value):
        return tuple(s for s in suggestions if any(fnmatch.fnmatchcase(name, value) for name in names_of(s)))
    return tuple(s for s in suggestions if value in names_of(s))


def filtered(text: str, suggestions: tuple[Suggestion, ...]) -> tuple[Suggestion, ...]:
    """
    The suggestions for what is typed: all for nothing, those a pattern matches, else those with the text in a name or
    the detail (any case).
    """
    if not text:
        return suggestions
    if is_pattern(text):
        return known_matches(text, suggestions)
    folded = text.casefold()
    return tuple(s for s in suggestions if any(folded in name.casefold() for name in (*names_of(s), s.detail)))


def spans(text: str, query: str) -> list[tuple[int, int]]:
    """
    Where `query` matches in `text`, as (start, end) pairs: each place the text has it (any case), or for a pattern
    the parts that are no wildcards, in their order.
    """
    if not query:
        return []
    if not is_pattern(query):
        return [(m.start(), m.end()) for m in re.finditer(re.escape(query), text, re.IGNORECASE)]
    if not fnmatch.fnmatchcase(text, query):
        return []
    found: list[tuple[int, int]] = []
    start = 0
    for literal in re.split(r"[*?]+", query):
        if not literal:
            continue
        at = text.find(literal, start)
        if at < 0:
            break
        found.append((at, at + len(literal)))
        start = at + len(literal)
    return found


def matches_text(value: str, suggestions: tuple[Suggestion, ...]) -> tuple[str, bool]:
    """
    What a value names, in a few words, and whether that is something: "Matches Speaker (not there now)",
    "Matches 2: WH-1000XM4, Buds Pro", "Matches nothing known".
    """
    found = known_matches(value, suggestions)
    if not found:
        return "Matches nothing known: it may come later", False

    def named(suggestion: Suggestion) -> str:
        name = suggestion.detail or suggestion.value
        return name if suggestion.present else f"{name}, not there now"

    if len(found) == 1:
        return f"Matches {named(found[0])}", True
    shown = ", ".join(named(suggestion) for suggestion in found[:3])
    more = f" and {len(found) - 3} more" if len(found) > 3 else ""
    first = " (the first one that is there)" if is_pattern(value) else ""
    return f"Matches {len(found)}: {shown}{more}{first}", True
