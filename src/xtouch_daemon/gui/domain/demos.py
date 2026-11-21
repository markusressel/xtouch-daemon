"""
Previews of the controls of a strip: the options of a channel grouped by the part of the strip they are about (the
encoder, the display, the buttons, the fader and meter), and for each part a short scene that shows what the values
do on the device, frame by frame with a caption. See `docs/development/design/control-previews.md`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, assert_never, cast

from pydantic import ValidationError

from xtouch_daemon.config.bindings import RunAction
from xtouch_daemon.config.buttons import (
    BUTTON_NAMES,
    LEDS,
    Action,
    ButtonName,
    ButtonSetup,
    LaunchAction,
    LedShows,
    default_setup,
    describe_action,
    indicator,
    table_of,
)
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.config.values import ENCODERS, default_encoder
from xtouch_daemon.gui.domain.looks import DARK
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import StripState
from xtouch_daemon.strips.base import UNITY, fader_position
from xtouch_daemon.strips.knobs import RING_CENTER, balance_text, ring_position

type Part = Literal["encoder", "display", "buttons", "fader"]
type Group = Literal["controls", "encoder", "display", "buttons", "fader", "slots"]

GROUPS: tuple[tuple[Group, str], ...] = (
    ("controls", "What it controls"),
    ("encoder", "Encoder"),
    ("display", "Display"),
    ("buttons", "Buttons"),
    ("fader", "Fader and meter"),
    ("slots", "Slots"),
)
"""The groups of the options of a channel, in the order of the device from top to bottom, with their titles."""
PARTS: dict[Group, frozenset[str]] = {
    "encoder": frozenset({"encoder"}),
    "display": frozenset({"label", "color", "talking_color", "lit_when_idle"}),
    "buttons": frozenset({"rec", "solo", "select"}),
    "fader": frozenset({"fader", "min_volume", "max_volume", "meter", "meter_point"}),
    "slots": frozenset({"absent_after", "in_pool", "tags"}),
}
"""The options of each group but "controls", which has the rest (what the strip controls)."""

PREVIEWED: frozenset[Group] = frozenset({"encoder", "display", "buttons", "fader"})
"""The groups about a part of the strip, which have a preview."""

LEVEL = 10
"""The level of the meter of audio that plays, of `protocol.METER_MAX`."""
VOLUME = 60
"""The volume the scenes start at."""

DEVICE_TYPES = frozenset({"output", "input"})


def group_of(option: str) -> Group:
    """The group of an option of a channel."""
    for group, options in PARTS.items():
        if option in options:
            return group
    return "controls"


@dataclass(frozen=True)
class Frame:
    caption: str
    """What happens, e.g. "An application records"."""
    state: StripState
    """What the strip shows then."""


@dataclass(frozen=True)
class Strip:
    """What a scene needs to know about the strip: its type and its options, unset ones at their defaults."""

    strip_type: str
    """The type of its strip: "output", "input", "apps", "auto", "voip", "homeassistant" or "custom"."""
    values: Mapping[str, Any]
    behavior: BehaviorConfig

    def value(self, name: str) -> Any:
        return self.values.get(name)

    def button(self, name: ButtonName) -> ButtonSetup:
        """What a button does: its table, the rest as the strip type does it."""
        default = default_setup(
            name,
            self.strip_type,
            devices=bool(self.value("device") or self.value("choices")),
            profiles=bool(self.value("profiles")),
            launch=self.value("launch") is not None,
        )
        table = table_of(name, self.value(name))
        parts: Mapping[str, Any] = table if isinstance(table, Mapping) else {}
        led = parts.get("led")
        return ButtonSetup(
            _action(parts.get("press"), default.press),
            _action(parts.get("hold"), default.hold),
            cast(LedShows, led) if led in LEDS.meanings else default.led,
        )

    @property
    def label(self) -> str:
        label = self.value("label")
        if label:
            return str(label)[: protocol.LCD_CELL_WIDTH]
        person = self.value("person")
        if self.strip_type == "voip":
            return (person[0] if isinstance(person, list | tuple) and person else "Alice")[: protocol.LCD_CELL_WIDTH]
        return {"output": "Output", "input": "Input", "auto": "Firefox"}.get(self.strip_type, "Label")

    def labels(self) -> tuple[tuple[str, str], ...]:
        """
        The labels the LCD shows for the choices (Select) or the profiles (Rec), with what picks each: the label of an
        entry, else the start of its device (the daemon takes the start of its description). Empty without them.
        """
        for name, button in (("choices", "Select"), ("profiles", "Rec")):
            entries = self.value(name)
            if isinstance(entries, list | tuple) and entries:
                return tuple(
                    (button, str(entry.get("label") or entry.get("device") or "?")[: protocol.LCD_CELL_WIDTH])
                    for entry in entries
                    if isinstance(entry, Mapping)
                )
        return ()

    @property
    def color(self) -> str:
        return str(self.value("color") or "white")

    @property
    def volume_range(self) -> tuple[int, int]:
        bottom = self.value("min_volume")
        top = self.value("max_volume")
        return (0 if bottom is None else int(bottom)), (self.behavior.max_volume if top is None else int(top))

    def fraction(self, volume: float) -> float:
        bottom, top = self.volume_range
        return fader_position(volume, bottom, top, self.behavior.unity_at)

    @property
    def meter_point(self) -> str:
        return str(self.value("meter_point") or self.behavior.meter_point)

    def playing(self, volume: int = VOLUME, text: str | None = None) -> StripState:
        """The strip while audio plays at `volume`: lit, its label and volume, the fader there."""
        ring = ring_position(self.fraction(volume))
        return StripState(
            color=self.color,
            text=(self.label, f"{volume}%" if text is None else text),
            leds=dict(DARK.leds),
            ring=ring,
            ring_mode="wrap",
            fader=self.fraction(volume),
            touched=False,
            meter=LEVEL if self.value("meter") is not False else 0,
        )


def _action(value: object, default: Action) -> Action:
    """An action of the form, `default` for none (or one that is no action, which the form shows as a problem)."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        try:
            return RunAction.model_validate(value) if "run" in value else LaunchAction.model_validate(value)
        except ValidationError:
            return default
    return default


def scene(part: Part, strip: Strip) -> tuple[Frame, ...]:
    """The frames that show what the options of `part` do on `strip`."""
    match part:
        case "encoder":
            return _encoder(strip)
        case "display":
            return _display(strip)
        case "buttons":
            return _buttons(strip)
        case "fader":
            return _fader(strip)
        case _ as unreachable:
            assert_never(unreachable)


def _encoder(strip: Strip) -> tuple[Frame, ...]:
    base = strip.playing()
    if strip.strip_type not in ENCODERS:
        # bindings: done by the GUI (the encoder of a custom channel)
        return tuple(
            Frame(
                f"Turned: the value is {value}",
                replace(base, ring=ring_position(value / 100), text=(strip.label, str(value)), meter=0),
            )
            for value in (40, 45, 50)
        )
    mode = strip.value("encoder") or default_encoder(strip.strip_type, strip.value("fader") or "volume")
    match mode:
        case "volume":
            step = max(strip.behavior.encoder_step, 5)
            frames = [Frame("Plays", base)]
            for volume in range(VOLUME + step, VOLUME + 3 * step + 1, step):
                frames.append(Frame(f"Turned right: {volume} %", strip.playing(volume)))
            reset = strip.behavior.reset_volume
            frames.append(Frame(f"Pushed: back to {reset} %", strip.playing(reset)))
            return tuple(frames)
        case "balance":
            frames = [
                Frame("Centered", replace(base, ring=RING_CENTER, ring_mode="boost_cut", text=(strip.label, "center")))
            ]
            for balance in (0.2, 0.4, 0.6):
                offset = round(balance * (RING_CENTER - 1))
                state = replace(
                    base, ring=RING_CENTER + offset, ring_mode="boost_cut", text=(strip.label, balance_text(balance))
                )
                frames.append(Frame(f"Turned right: {balance_text(balance)}", state))
            centered = replace(base, ring=RING_CENTER, ring_mode="boost_cut", text=(strip.label, "center"))
            frames.append(Frame("Pushed: centered", centered))
            return tuple(frames)
        case "pick":
            apps = ("Firefox", "Spotify", "Discord", "mpv")
            frames = []
            for index, app in enumerate(apps):
                ring = ring_position(index / (len(apps) - 1))
                state = replace(base, ring=ring, ring_mode="dot", text=(app, f"{VOLUME}%"))
                frames.append(Frame(f"Turned: application {index + 1} of {len(apps)}", state))
            pinned = replace(frames[-1].state, ring_mode="wrap")
            frames.append(Frame("Pushed: pinned, it stays after it stopped", pinned))
            return tuple(frames)
        case "media":
            frames = []
            for second, progress in ((30, 0.3), (35, 0.35), (40, 0.4)):
                state = replace(base, ring=ring_position(progress), text=(strip.label, f"0:{second}"))
                frames.append(Frame(f"Turned right: 5 s later in the track ({second} s)", state))
            frames.append(Frame("Pushed: paused", replace(frames[-1].state, text=(strip.label, "paused"))))
            return tuple(frames)
        case _:
            frames = []
            for value in (40, 45, 50):
                state = replace(base, ring=ring_position(value / 100), text=(strip.label, f"{value}%"))
                frames.append(Frame(f"Turned: the number in Home Assistant is {value}", state))
            frames.append(Frame("Pushed: an event in Home Assistant", frames[-1].state))
            return tuple(frames)


def _idle(strip: Strip, base: StripState) -> StripState:
    """The strip while it has nothing to control: dark, or lit with `lit_when_idle`; the fader down."""
    text = "off" if strip.strip_type in DEVICE_TYPES else "idle"
    color = strip.color if strip.value("lit_when_idle") else "off"
    return replace(base, color=color, text=(strip.label, text), fader=0.0, meter=0, ring=0)


def _display(strip: Strip) -> tuple[Frame, ...]:
    base = strip.playing()
    if strip.strip_type == "voip":
        talking = str(strip.value("talking_color") or "green")
        return (
            Frame("There, quiet", replace(base, text=(strip.label, ""), meter=0)),
            Frame("Talks", replace(base, color=talking, text=(strip.label, "talks"))),
            Frame("Muted by you", replace(base, text=(strip.label, "muted"), meter=0)),
            Frame("Away", replace(base, color="off", text=(strip.label, "away"), fader=0.0, meter=0)),
        )
    if strip.strip_type == "custom":
        return (
            Frame("Shows the value", replace(base, text=(strip.label, "50"), meter=0)),
            Frame("The fader moves: the new value", replace(base, text=(strip.label, "72"), fader=0.72, meter=0)),
        )
    if strip.strip_type == "homeassistant":
        return (
            Frame("Shows the label", replace(base, text=(strip.label, "50%"), meter=0)),
            Frame("The fader moves: the new value", replace(base, text=(strip.label, "72%"), fader=0.72, meter=0)),
        )
    idle = "lit (lit_when_idle)" if strip.value("lit_when_idle") else "dark"
    labels = strip.labels()
    if labels:
        # the label of the entry picked first, then one picked after the other
        base = replace(base, text=(labels[0][1], base.text[1]))
    return (
        Frame("Plays: label and volume", base),
        *(Frame(f"{button} picked {label}", replace(base, text=(label, base.text[1]))) for button, label in labels[1:]),
        Frame("Fader moved: the new volume", strip.playing(72)),
        Frame("Muted", replace(base, text=(strip.label, "muted"))),
        Frame(f"Nothing to control: {idle}", _idle(strip, base)),
    )


def _buttons(strip: Strip) -> tuple[Frame, ...]:
    """
    What the LEDs show in the situations their indicators are about, then what a press and a hold of each button
    that does something leads to (e.g. Select pressed: the device is the default, its LED lit).
    """
    base = strip.playing()
    device = strip.strip_type in DEVICE_TYPES
    setups = {name: strip.button(name) for name in BUTTON_NAMES}
    situations: list[tuple[str, set[str]]] = [("Audio plays", {"playing"})]
    situations.append(("An application records", {"playing", "recording"}))
    if device:
        situations.append(("The default device", {"default"}))
    situations.append(("Muted", {"playing", "muted"}))
    situations.append(("Nothing plays", set()))
    for name, setup in setups.items():
        for part, action in (("pressed", setup.press), ("held", setup.hold)):
            if action != "off":
                flags = {"playing", f"{name} {part}", *_ACTION_FLAGS.get(describe_action(action), ())}
                situations.append((f"{name.capitalize()} {part} ({_does(action)})", flags))
    frames = []
    for caption, flags in situations:
        leds = dict(DARK.leds)
        for name, setup in setups.items():
            if _lit(name, setup, flags):
                leds[name] = "on"
        if "muted" in flags:
            leds["mute"] = "on"
        lit = [name.capitalize() for name, led in leds.items() if led == "on"]
        frames.append(Frame(f"{caption}: {', '.join(lit) if lit else 'all dark'}", replace(base, leds=leds)))
    return tuple(frames)


def _does(action: Action) -> str:
    """What an action does, in a few words."""
    if isinstance(action, LaunchAction):
        return f"starts {action.launch[0]}"
    if not isinstance(action, str):
        return f"runs {action.run[0]}"
    if action.startswith("mode:"):
        return f"mode {action.removeprefix('mode:')}"
    if action.startswith("toggle:"):
        return f"{action.removeprefix('toggle:')} toggled"
    return _DOES.get(action, action)


_DOES = {
    "default": "makes it the default",
    "next": "shows the next one",
    "profile": "the next profile",
    "launch": "starts it",
    "talk": "talks while held",
    "mute_others": "the others muted while held",
    "homeassistant": "an event in Home Assistant",
    "cycle_modes": "the next mode",
}
"""What the actions do, for the captions of the preview."""

_ACTION_FLAGS = {"default": ("default",), "next": ("shown",)}
"""What an action leads to, for the LEDs that show it: the device is the default, the strip shows another one."""


def _lit(name: str, setup: ButtonSetup, flags: set[str]) -> bool:
    """Whether the LED of a button is lit in a situation (`flags`: what is so, and which button is pressed or held)."""
    if (shows := indicator(setup.led)) is not None:
        return shows in flags
    if setup.led == "shown":
        return "shown" in flags
    match setup.press:
        case "off" | "homeassistant":
            return False
        case "default":
            return "default" in flags
        case "next":
            return "shown" in flags
        case _:
            # after a press: the second profile, the application runs, the mode is on, while held
            return f"{name} pressed" in flags


def _fader(strip: Strip) -> tuple[Frame, ...]:
    base = strip.playing()
    if strip.value("fader") == "homeassistant" or strip.strip_type == "homeassistant":
        return tuple(
            Frame(
                f"The fader at {round(position * 100)} %: the number in Home Assistant",
                replace(base, fader=position, meter=0),
            )
            for position in (0.2, 0.5, 0.8)
        )
    bottom, top = strip.volume_range
    meter_on = strip.value("meter") is not False
    pre = strip.meter_point == "pre_fader"

    def at(volume: float, caption: str) -> Frame:
        level = LEVEL if pre else round(LEVEL * min(1.0, volume / UNITY))
        state = replace(base, fader=strip.fraction(volume), meter=level if meter_on else 0, touched=True)
        if not meter_on:
            meter = "no meter"
        elif pre:
            meter = "meter: the level before it"
        else:
            meter = "meter: follows it"
        return Frame(f"{caption}; {meter}", state)

    frames = [at(bottom, f"Bottom: {bottom} %")]
    if bottom < UNITY < top:
        frames.append(at(UNITY, "0 dB mark: 100 %"))
    frames.append(at(top, f"Top: {top} %"))
    muted_level = LEVEL if pre and strip.strip_type == "output" and meter_on else 0
    muted = replace(base, meter=muted_level, leds={**DARK.leds, "mute": "on"})
    shows = "still the level" if muted_level else "dark"
    frames.append(Frame(f"Muted; meter: {shows}", muted))
    return tuple(frames)
