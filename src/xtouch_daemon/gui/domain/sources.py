"""What the sound server has right now, as suggestions for the options that name devices and applications."""

from dataclasses import dataclass

from xtouch_daemon import presets
from xtouch_daemon.audio.model import AudioState, Direction


@dataclass(frozen=True)
class Suggestion:
    value: str
    """What goes into the option."""
    detail: str
    """What it is, for people."""
    tip: str = ""
    """More about it, e.g. what a preset stands for."""

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
        Suggestion(preset.entry, preset.description, preset_tip(preset.entry, kind))
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


def devices(state: AudioState, direction: Direction) -> tuple[Suggestion, ...]:
    """The devices for `device`, by node name, as `xtouch-daemon list-devices` lists them."""
    return tuple(
        Suggestion(device.name, device.description + (" (the default)" if state.is_default(device) else ""))
        for device in state.devices(direction)
    )


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
        Suggestion(profile.name, profile.description + (" (active)" if profile.name == card.profile else ""))
        for card in state.cards
        if card.name in cards
        for profile in card.profiles
    )


def cards(state: AudioState) -> tuple[Suggestion, ...]:
    """The sound cards by name, for `card` of `choices`: their descriptions and devices, as `list-devices` has them."""
    return tuple(
        Suggestion(
            card.name,
            ", ".join(
                part
                for part in (
                    card.description,
                    *(device.name for device in (*state.outputs, *state.inputs) if device.card == card.name),
                )
                if part
            ),
        )
        for card in state.cards
    )


def card_profiles(state: AudioState, card: str | None) -> tuple[Suggestion, ...]:
    """The profiles of the card of `card` (its name or description, wildcards allowed), for `profile` of `choices`."""
    found = state.card_matching(card) if card else None
    if found is None:
        return ()
    return tuple(
        Suggestion(profile.name, profile.description + (" (active)" if profile.name == found.profile else ""))
        for profile in found.profiles
    )
