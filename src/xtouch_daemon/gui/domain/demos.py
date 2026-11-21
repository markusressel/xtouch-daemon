"""
Previews of the controls of a strip: the options of a channel grouped by the part of the strip they are about (the
encoder, the display, the buttons, the fader and meter), and for each part a short scene that shows what the values
do on the device, frame by frame with a caption. See `docs/development/design/control-previews.md`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, assert_never, cast

from pydantic import ValidationError

from xtouch_daemon.config.bindings import HOME_ASSISTANT, LevelBinding, RunAction, ValueBinding, WatchBinding
from xtouch_daemon.config.buttons import (
    BUTTON_NAMES,
    LEDS,
    Action,
    ButtonName,
    ButtonSetup,
    LaunchAction,
    LedWord,
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
    "display": frozenset({"label", "lcd", "color", "talking_color", "lit_when_idle"}),
    "buttons": frozenset({"rec", "solo", "mute", "select"}),
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
CUSTOM = "custom"
CUSTOM_BUTTON_NAMES = (*BUTTON_NAMES, "mute")
"""The buttons of a `custom` channel: Mute is a button like the others there."""


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

    def button(self, name: str) -> ButtonSetup:
        """What a button does: its table, the rest as the strip type does it (nothing on a `custom` channel)."""
        default = (
            ButtonSetup()
            if self.strip_type == CUSTOM
            else default_setup(
                cast(ButtonName, name),
                self.strip_type,
                devices=bool(self.value("device") or self.value("choices")),
                profiles=bool(self.value("profiles")),
                launch=self.value("launch") is not None,
            )
        )
        table = table_of(name, self.value(name))
        parts: Mapping[str, Any] = table if isinstance(table, Mapping) else {}
        return ButtonSetup(
            _action(parts.get("press"), default.press),
            _action(parts.get("hold"), default.hold),
            _led(parts.get("led"), default.led),
        )

    @property
    def buttons(self) -> tuple[str, ...]:
        return CUSTOM_BUTTON_NAMES if self.strip_type == CUSTOM else BUTTON_NAMES

    def binding[T: ValueBinding | WatchBinding](self, name: str, model: type[T]) -> T | None:
        """The program a part is bound to, None for a word, nothing, or a table that is no binding (yet)."""
        value = self.value(name)
        if not isinstance(value, Mapping):
            return None
        try:
            return model.model_validate(value)
        except ValidationError:
            return None

    def fader_value(self) -> ValueBinding | None:
        return self.binding("fader", ValueBinding)

    def encoder_value(self) -> ValueBinding | None:
        """The value the encoder sets: its own, else on a `custom` channel that of the fader, by its `step`."""
        own = self.binding("encoder", ValueBinding)
        if own is None and self.strip_type == CUSTOM and self.value("encoder") is None:
            return self.fader_value()
        return own

    @property
    def label(self) -> str:
        label = self.value("label")
        if label:
            return str(label)[: protocol.LCD_CELL_WIDTH]
        targets = self.value("targets")
        if self.strip_type == CUSTOM and isinstance(targets, list | tuple) and targets:
            # the name of the target it controls
            first: Any = targets[0]
            if isinstance(first, Mapping) and first.get("name"):  # pyright: ignore[reportUnknownMemberType]
                return str(first["name"])[: protocol.LCD_CELL_WIDTH]  # pyright: ignore[reportUnknownArgumentType]
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
        """The backlight: a bound color is white until Home Assistant or the program says otherwise."""
        color = self.value("color")
        return color if isinstance(color, str) and color and color != HOME_ASSISTANT else "white"

    @property
    def meter_level(self) -> int:
        """The meter while audio plays: dark when it is off, or on a `custom` channel without one."""
        meter = self.value("meter")
        if meter is False or (self.strip_type == CUSTOM and meter is None):
            return 0
        return LEVEL

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
            meter=self.meter_level,
        )


def _led(value: object, default: LedWord | WatchBinding) -> LedWord | WatchBinding:
    """What an LED of the form shows, `default` for none or for one that shows nothing (the form shows its problem)."""
    if isinstance(value, Mapping):
        try:
            return WatchBinding.model_validate(value)
        except ValidationError:
            return default
    return cast(LedWord, value) if value in LEDS.meanings else default


def value_text(binding: ValueBinding, value: float) -> str:
    """A value as the LCD shows it, in the `format` of the binding."""
    try:
        return binding.format.format(value=value)[: protocol.LCD_CELL_WIDTH]
    except ValueError, KeyError, IndexError:
        return f"{value:g}"


def _program(argv: tuple[str, ...]) -> str:
    """The name of a program, for a caption."""
    return argv[0].rsplit("/", 1)[-1]


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
    if (binding := strip.encoder_value()) is not None:
        return _turns(strip, binding)
    if strip.strip_type not in ENCODERS and strip.value("encoder") != HOME_ASSISTANT:
        # a custom channel with neither a value of the encoder nor of the fader
        return (Frame("Turned: nothing, the encoder is not bound", replace(base, ring=0, text=(strip.label, ""))),)
    own = strip.value("encoder")
    # a table that is no value yet: what the type does, the form shows its problem
    mode = own if isinstance(own, str) and own else default_encoder(strip.strip_type, strip.value("fader") or "volume")
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


def _turns(strip: Strip, binding: ValueBinding) -> tuple[Frame, ...]:
    """An encoder that sets a value of your own: three steps of it from the middle, then a push."""
    span = binding.max - binding.min
    step = binding.step if binding.step is not None else span * strip.behavior.encoder_step / 100
    base = replace(strip.playing(), meter=strip.meter_level)
    frames: list[Frame] = []
    for index in range(3):
        value = min(binding.max, binding.min + span / 2 + index * step)
        fraction = (value - binding.min) / span
        text = value_text(binding, value)
        state = replace(base, ring=ring_position(fraction), text=(strip.label, text))
        frames.append(Frame(f"Turned right: {text}, set by {_program(binding.set)}", state))
    if binding.push is not None:
        text = value_text(binding, binding.push)
        state = replace(base, ring=ring_position((binding.push - binding.min) / span), text=(strip.label, text))
        frames.append(Frame(f"Pushed: {text}", state))
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
    if strip.strip_type == CUSTOM:
        return _custom_display(strip)
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
    lcd = _bound_lcd(strip)
    return (
        Frame("Plays: label and volume", base),
        *((Frame(lcd[0], replace(base, text=(base.text[0], lcd[1]))),) if lcd is not None else ()),
        *((Frame(f"Lit in {color}", base),) if (color := _bound_color(strip)) is not None else ()),
        *(Frame(f"{button} picked {label}", replace(base, text=(label, base.text[1]))) for button, label in labels[1:]),
        Frame("Fader moved: the new volume", strip.playing(72)),
        Frame("Muted", replace(base, text=(strip.label, "muted"))),
        Frame(f"Nothing to control: {idle}", _idle(strip, base)),
    )


def _bound_lcd(strip: Strip) -> tuple[str, str] | None:
    """The second line of the LCD when it is bound: the caption and the text; None when it shows what the type says."""
    if strip.value("lcd") == HOME_ASSISTANT:
        return "The second line: the text Home Assistant sets", "HA text"
    if (watch := strip.binding("lcd", WatchBinding)) is not None:
        return f"The second line: each line {_program(watch.watch)} prints", "line"
    return None


def _bound_color(strip: Strip) -> str | None:
    """Where the color comes from when it is bound, for a caption; None for a color of the file."""
    if strip.value("color") == HOME_ASSISTANT:
        return "the color Home Assistant sets"
    if (watch := strip.binding("color", WatchBinding)) is not None:
        return f"the color {_program(watch.watch)} prints"
    return None


def _custom_display(strip: Strip) -> tuple[Frame, ...]:
    """The LCD of a `custom` channel: its label, and what `lcd` shows, else the value of the fader or the encoder."""
    base = replace(strip.playing(), meter=strip.meter_level)
    frames: list[Frame] = []
    color = _bound_color(strip)
    lit = f", lit in {color}" if color is not None else ""
    if (lcd := _bound_lcd(strip)) is not None:
        frames.append(Frame(lcd[0] + lit, replace(base, text=(strip.label, lcd[1]))))
    elif (binding := strip.fader_value() or strip.encoder_value()) is not None:
        span = binding.max - binding.min
        for caption, fraction in (("Shows the value", 0.5), ("The value changes: the new one", 0.72)):
            text = value_text(binding, binding.min + fraction * span)
            frames.append(Frame(caption + lit, replace(base, text=(strip.label, text))))
    else:
        frames.append(Frame("Shows the label: no value, no lcd" + lit, replace(base, text=(strip.label, ""))))
    targets = strip.value("targets")
    names = [
        str(target.get("name"))[: protocol.LCD_CELL_WIDTH]  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        for target in (targets if isinstance(targets, list | tuple) else ())  # pyright: ignore[reportUnknownVariableType]
        if isinstance(target, Mapping) and target.get("name")  # pyright: ignore[reportUnknownMemberType]
    ]
    if len(names) > 1 and not strip.value("label") and not strip.value("together"):
        last = frames[-1].state
        frames.append(Frame(f"The next target: {names[1]}", replace(last, text=(names[1], last.text[1]))))
    return tuple(frames)


def _buttons(strip: Strip) -> tuple[Frame, ...]:
    """
    What the LEDs show in the situations their indicators are about, then what a press and a hold of each button
    that does something leads to (e.g. Select pressed: the device is the default, its LED lit).
    """
    base = replace(strip.playing(), meter=strip.meter_level)
    device = strip.strip_type in DEVICE_TYPES
    setups = {name: strip.button(name) for name in strip.buttons}
    situations: list[tuple[str, set[str]]] = []
    if strip.strip_type == CUSTOM:
        situations.append(("Nothing pressed", set()))
    else:
        situations.append(("Audio plays", {"playing"}))
        situations.append(("An application records", {"playing", "recording"}))
        if device:
            situations.append(("The default device", {"default"}))
        situations.append(("Muted", {"playing", "muted"}))
        situations.append(("Nothing plays", set()))
    leds = [setup.led for setup in setups.values()]
    for led in leds:
        if isinstance(led, WatchBinding):
            situations.append((f"{_program(led.watch)} prints on", {"playing", "watch"}))
            break
    if HOME_ASSISTANT in leds:
        situations.append(("Home Assistant turns an LED on", {"playing", "homeassistant"}))
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
        if "muted" in flags and strip.strip_type != CUSTOM:
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
    if isinstance(setup.led, WatchBinding):
        return "watch" in flags
    if setup.led in ("shown", HOME_ASSISTANT):
        return setup.led in flags
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
    bound_meter = _bound_meter(strip)
    if strip.value("fader") == "homeassistant" or strip.strip_type == "homeassistant":
        return tuple(
            Frame(
                f"The fader at {round(position * 100)} %: the number in Home Assistant"
                + (f"; {bound_meter}" if bound_meter else ""),
                replace(base, fader=position, meter=LEVEL if bound_meter else 0),
            )
            for position in (0.2, 0.5, 0.8)
        )
    if (binding := strip.fader_value()) is not None or strip.strip_type == CUSTOM:
        return _moves(strip, binding, bound_meter)
    bottom, top = strip.volume_range
    meter_on = strip.value("meter") is not False
    pre = strip.meter_point == "pre_fader"

    def at(volume: float, caption: str) -> Frame:
        level = LEVEL if pre or bound_meter else round(LEVEL * min(1.0, volume / UNITY))
        state = replace(base, fader=strip.fraction(volume), meter=level if meter_on else 0, touched=True)
        if bound_meter:
            meter = bound_meter
        elif not meter_on:
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
    muted_level = LEVEL if ((pre and strip.strip_type == "output") or bound_meter) and meter_on else 0
    muted = replace(base, meter=muted_level, leds={**DARK.leds, "mute": "on"})
    shows = "still the level" if muted_level else "dark"
    frames.append(Frame(f"Muted; meter: {shows}", muted))
    return tuple(frames)


def _bound_meter(strip: Strip) -> str | None:
    """What the meter shows when it is bound, for a caption; None for the level of the audio (or none)."""
    if strip.value("meter") == HOME_ASSISTANT:
        return "meter: the level Home Assistant sets"
    if (watch := strip.binding("meter", LevelBinding)) is not None:
        return f"meter: each number {_program(watch.watch)} prints"
    return None


def _moves(strip: Strip, binding: ValueBinding | None, meter: str | None) -> tuple[Frame, ...]:
    """A fader that sets a value of your own (or, on a `custom` channel, nothing): bottom, middle and top."""
    base = replace(strip.playing(), meter=LEVEL if meter else 0)
    if binding is None:
        caption = "The fader stays down: it is not bound" + (f"; {meter}" if meter else "")
        return (Frame(caption, replace(base, fader=0.0, ring=0, text=(strip.label, base.text[1]))),)
    frames: list[Frame] = []
    for where, fraction in (("Bottom", 0.0), ("Middle", 0.5), ("Top", 1.0)):
        text = value_text(binding, binding.min + fraction * (binding.max - binding.min))
        caption = f"{where}: {text}, set by {_program(binding.set)}" + (f"; {meter}" if meter else "")
        frames.append(Frame(caption, replace(base, fader=fraction, touched=True, text=(strip.label, text))))
    return tuple(frames)
