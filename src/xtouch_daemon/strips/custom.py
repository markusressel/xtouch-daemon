"""
Custom channels (`type = "custom"`): a strip whose parts do what they are bound to, e.g. a fader that sets the
brightness of a screen with programs of your own, a color that a `watch` prints, an LED of Home Assistant. An unbound
part is dark and does nothing.

With `targets`, the programs run once per target (`{target}` is its `value`): each target has values and watches of
its own, and they all run all the time. The strip controls one target at a time; `next` switches, and the name of the
new one shows on the second line of the LCD for NOTICE_TIME. With `together`, a hand sets every target, and the strip
shows the first one. Programs without `{target}` run once for all targets.

The fader and the encoder of `[controls]` that name the channel set its values too: it is their `ValueSource`. `present`
tells the slots whether the channel is there (`presence`, `on_presence`).
"""

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import get_args

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.event import MQTTEvent
from haad_mqtt_autodiscovery.entity.number import MQTTNumber
from haad_mqtt_autodiscovery.entity.select import MQTTSelect

from xtouch_daemon.audio.meter import Lit
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.bindings import (
    HOME_ASSISTANT,
    LevelBinding,
    RunAction,
    Target,
    ValueBinding,
    WatchBinding,
    fill,
    placeholders_of,
)
from xtouch_daemon.config.buttons import HOLD_TIME, Action, ButtonSetup, LaunchAction
from xtouch_daemon.config.strips import CustomButtonName, CustomStripConfig
from xtouch_daemon.config.values import ColorName, MeterPoint, color_of
from xtouch_daemon.hardware.protocol import METER_MAX, Button, Color, Led, RingMode
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.mqtt import MqttBridge
from xtouch_daemon.strips.base import NOTICE_TIME, Identity, Look, StripController, StripEnv
from xtouch_daemon.strips.homeassistant import (
    COLORS,
    FADER_PUBLISH_INTERVAL,
    LEDS,
    EncoderLink,
    FaderLink,
    LatestValue,
    LcdText,
    StripEntities,
    value_step,
)
from xtouch_daemon.strips.knobs import ring_position
from xtouch_daemon.strips.value import CommandValue, WatchedLine, color_of_line, led_of_line, level_of_line, value_text
from xtouch_daemon.system.commands import CommandError, Commands

_LOGGER = logging.getLogger(__name__)

BUTTONS: dict[Button, CustomButtonName] = {
    Button.SELECT: "select",
    Button.REC: "rec",
    Button.SOLO: "solo",
    Button.MUTE: "mute",
}
"""The buttons of a custom channel: Mute is a button like the others."""
assert set(BUTTONS.values()) == set(get_args(CustomButtonName))


class TogetherValue(CommandValue):
    """The value of the first target with `together`: what a hand sets, every other target gets too (`followers`)."""

    followers: tuple[CommandValue, ...] = ()

    def set(self, value: float) -> None:
        super().set(value)
        for follower in self.followers:
            follower.set(value)


class Programs:
    """
    The values and watches of one target (of the channel, without targets). Programs that are the same for two
    targets (without `{target}`) are one: `shared` has them by their program.
    """

    def __init__(
        self,
        config: CustomStripConfig,
        commands: Commands,
        encoder_step: int,
        name: str,
        target: Target | None,
        shared: dict[tuple[object, ...], CommandValue | WatchedLine],
        first: bool,
    ):
        self.target = target
        self._commands = commands
        self._step = encoder_step
        self._name = name
        self._placeholders = {"target": target.value} if target is not None else {}
        self._shared = shared
        self._first = first and config.together
        self.fader = self._value(config.fader, "fader")
        self.encoder = self._value(config.encoder, "encoder")
        self._fine_fader = config.encoder is None
        self.lcd = self._line(config.lcd, "lcd")
        self.color = self._line(config.color, "color")
        self.meter = self._line(config.meter, "meter")
        self.present = self._line(config.present, "present")
        self.leds = {
            button: line for button, name in BUTTONS.items() if (line := self._line(config.button(name).led, name))
        }

    @property
    def title(self) -> str:
        return self._name if self.target is None else f"{self._name} ({self.target.name})"

    def _value(self, part: object, what: str) -> CommandValue | None:
        if not isinstance(part, ValueBinding):
            return None
        programs = tuple(tuple(fill(argv, **self._placeholders)) for argv in part.programs.values())
        # the first target makes it: with `together`, it leads
        key = (what, programs)
        if (value := self._shared.get(key)) is None:
            kind = TogetherValue if self._first else CommandValue
            value = kind(part, self._commands, self._step, f"{self.title}.{what}", self._placeholders)
            self._shared[key] = value
        assert isinstance(value, CommandValue)
        return value

    def _line(self, part: object, what: str) -> WatchedLine | None:
        if not isinstance(part, WatchBinding):
            return None
        argv = tuple(fill(part.watch, **self._placeholders))
        if (line := self._shared.get(("watch", argv))) is None:
            line = WatchedLine(argv, self._commands, f"{self.title}.{what}")
            self._shared[("watch", argv)] = line
        assert isinstance(line, WatchedLine)
        return line

    def knob(self) -> CommandValue | None:
        """What the encoder sets: its own value, else (without an encoder of its own) the fader's."""
        return self.encoder or (self.fader if self._fine_fader else None)

    def run_value(self) -> CommandValue | None:
        """The value of `{value}` in `run`: the fader's, else the encoder's."""
        return self.fader or self.encoder


class HomeAssistantParts:
    """
    The parts of a custom channel in Home Assistant: those bound to `"homeassistant"`, by the entities of the
    `homeassistant` strip type, and the values of programs of your own as numbers from their `min` to `max`.
    """

    def __init__(self, strip: Strip, env: StripEnv, bridge: MqttBridge, identity: Identity, config: CustomStripConfig):
        self.bridge = bridge
        self._tasks: set[asyncio.Task[None]] = set()
        entities = StripEntities(bridge, identity)
        namespace, device, title, strip_id = entities.namespace, entities.device, entities.title, identity.id
        self.fader = FaderLink(strip, entities.number("fader")) if config.fader == HOME_ASSISTANT else None
        self.encoder = (
            EncoderLink(strip, entities.number("encoder"), env.behavior.encoder_step)
            if config.encoder == HOME_ASSISTANT
            else None
        )
        self.meter = entities.number("meter") if config.meter == HOME_ASSISTANT else None
        self.bottom = (
            LcdText(namespace, f"{strip_id}_bottom", f"{title} bottom line", device=device)
            if config.lcd == HOME_ASSISTANT
            else None
        )
        self.color = (
            MQTTSelect(
                namespace,
                f"{strip_id}_color",
                f"{title} color",
                options=list(COLORS),
                icon="mdi:palette",
                device=device,
            )
            if config.color == HOME_ASSISTANT
            else None
        )
        self.leds: dict[Button, MQTTSelect] = {}
        pressed: list[str] = []
        for button, name in BUTTONS.items():
            setup = config.button(name)
            if setup.led == HOME_ASSISTANT:
                self.leds[button] = MQTTSelect(
                    namespace, f"{strip_id}_{name}_led", f"{title} {name} LED", options=list(LEDS), device=device
                )
            if setup.press == HOME_ASSISTANT:
                pressed.append(name)
        event_types = [
            *(["fader_touched", "fader_released"] if self.fader is not None else []),
            *(["encoder_pressed", "encoder_released"] if self.encoder is not None else []),
            *(f"{name}_{action}" for name in pressed for action in ("pressed", "released")),
        ]
        self.events: MQTTEvent | None = entities.events(event_types) if event_types else None
        self.values: dict[str, LatestValue] = {}
        """The numbers of the values of programs of your own, by part (`fader`, `encoder`)."""
        for part in ("fader", "encoder"):
            binding = getattr(config, part)
            if isinstance(binding, ValueBinding):
                number = MQTTNumber(
                    namespace,
                    f"{strip_id}_{part}",
                    f"{title} {part}",
                    device=device,
                    min_val=binding.min,
                    max_val=binding.max,
                    step=value_step(part, binding, env),
                    mode="slider",
                )
                self.values[part] = LatestValue(number, FADER_PUBLISH_INTERVAL)
        watched: list[MQTTEntity] = [
            entity
            for entity in (
                self.fader.entity if self.fader is not None else None,
                self.encoder.entity if self.encoder is not None else None,
                self.meter,
                self.bottom,
                self.color,
                *self.leds.values(),
            )
            if entity is not None
        ]
        self.watched = watched
        """The entities whose states Home Assistant sets (the strip shows them)."""
        self.entities: dict[MQTTEntity, str | None] = {
            **{entity: "0" for entity in watched if isinstance(entity, MQTTNumber)},
            **({self.bottom: ""} if self.bottom is not None else {}),
            **({self.color: "white"} if self.color is not None else {}),
            **dict.fromkeys(self.leds.values(), "off"),
            **dict.fromkeys((value.entity for value in self.values.values()), None),
            **({self.events: None} if self.events is not None else {}),
        }

    def event(self, event_type: str) -> None:
        """An event of a part, while Home Assistant is there."""
        if self.events is not None and self.bridge.ready:
            task = asyncio.create_task(self.events.trigger(event_type), name=f"{self.events.entity_id}: {event_type}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def close(self) -> None:
        for link in (self.fader, self.encoder):
            if link is not None:
                link.close()
        for value in self.values.values():
            value.cancel()
        for task in self._tasks:
            task.cancel()
        for entity in self.entities:
            self.bridge.unwatch(entity)


class CustomStrip(StripController):
    """
    The strip of a custom channel: each part shows and does what it is bound to (see the module). An encoder without a
    binding of its own sets the fader's value, by its `step`. Select, Rec, Solo and Mute do what their press and hold
    say: a hold once the button is down for HOLD_TIME, a press when it is let go before (at once without a hold).
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        look: Look,
        config: CustomStripConfig,
        commands: Commands,
    ):
        super().__init__(strip, env, identity, look)
        self.config = config
        self.commands = commands
        self.listeners: list[Callable[[], None]] = []
        """Called when the values are others: the strip switched to another target (`ValueSource`)."""
        self.on_presence: Callable[[], None] = lambda: None
        """Called when `presence` changed."""
        self._shared: dict[tuple[object, ...], CommandValue | WatchedLine] = {}
        targets: tuple[Target | None, ...] = config.targets or (None,)
        self.targets = [
            Programs(config, commands, env.behavior.encoder_step, identity.name, target, self._shared, index == 0)
            for index, target in enumerate(targets)
        ]
        """The values and watches of each target (one without targets)."""
        if config.together:
            first = self.targets[0]
            for part in ("fader", "encoder"):
                leader = getattr(first, part)
                if isinstance(leader, TogetherValue):
                    others = (getattr(programs, part) for programs in self.targets[1:])
                    leader.followers = tuple({id(v): v for v in others if v is not None and v is not leader}.values())
        self.index = 0
        """The target the strip controls now."""
        self._presence = self.presence
        self._colors: dict[int, ColorName] = {}
        """The last color each watch of `color` printed, by the id of its `WatchedLine`: other lines keep it."""
        for thing in self._shared.values():
            thing.listeners.append(self._changed)
        self.ha: HomeAssistantParts | None = None
        # (Simulate has no MQTT: its parts in Home Assistant look as while it is not there; the configuration makes
        # sure the device has [mqtt] for them)
        if env.bridge is not None and (config.uses_home_assistant or config.value_bound):
            self.ha = HomeAssistantParts(strip, env, env.bridge, identity, config)
            for entity in self.ha.watched:
                env.bridge.watch(entity, lambda _: self.show())
            for part, number in self.ha.values.items():
                # once Home Assistant is there (and again after a reconnect), it learns the values
                env.bridge.watch(number.entity, lambda _: self._publish_values())
                env.bridge.watch_commands(number.entity, lambda payload, part=part: self._commanded(part, payload))
        self.notice: str | None = None
        """Shown on the second line for a moment (`notify()`): the name of a new target, a value set by hand."""
        self._notice_timer: asyncio.TimerHandle | None = None
        self._holds: dict[Button, asyncio.TimerHandle] = {}
        """The buttons pressed whose hold comes once HOLD_TIME is over."""
        self._running: dict[Button, int] = {}
        """The buttons whose `run` still runs, with how many runs (their LED with `led = "press"`)."""
        self._closed = False
        self._gripped: CommandValue | None = None
        """The value the finger on this strip's fader holds: the only one whose touch it sets and clears."""

    # -- what it controls -----------------------------------------------------------------------------------------

    @property
    def current(self) -> Programs:
        """The values and watches of the target the strip controls now."""
        return self.targets[self.index]

    @property
    def target(self) -> Target | None:
        return self.current.target

    def fader_value(self) -> CommandValue | None:
        return self.current.fader

    def encoder_value(self) -> CommandValue | None:
        return self.current.encoder

    def switch(self, steps: int = 1) -> None:
        """Controls the next target (`steps` on): its name shows for NOTICE_TIME, the claims of `[controls]` follow."""
        if len(self.targets) < 2:
            return
        self.index = (self.index + steps) % len(self.targets)
        target = self.target
        assert target is not None
        _LOGGER.info(f"{self.identity.name}: {target.name}")
        if self._gripped is not None:
            # the finger on the fader goes over to the value of the new target
            self._grip(self.current.fader)
        for listener in list(self.listeners):
            listener()
        self._publish_values()
        self.notify(target.name)
        self.show()

    @property
    def presence(self) -> bool | None:
        """
        Whether the channel is there by `present`: while one of its watches (one per target with `{target}`) printed a
        line with text last. True without `present`; None while it is not known yet (no line so far, none with text).
        """
        lines = list({id(p.present): p.present for p in self.targets if p.present is not None}.values())
        if not lines:
            return True
        if any(line.line is not None and line.line.strip() for line in lines):
            return True
        return None if any(line.line is None for line in lines) else False

    @property
    def absent(self) -> bool:
        """Whether `present` says the channel is not there: the strip is dark and does nothing, as an absent device."""
        return self.presence is False

    def _changed(self) -> None:
        """A value or a watch changed: it shows, Home Assistant learns the values, the slots the presence."""
        for programs in self.targets:
            line = programs.color
            if line is not None and (name := color_of_line(line.line or "")) is not None:
                self._colors[id(line)] = name
        self._publish_values()
        presence = self.presence
        if presence != self._presence:
            self._presence = presence
            self.on_presence()
        self.show()

    # -- Home Assistant ---------------------------------------------------------------------------------------------

    def _publish_values(self) -> None:
        """
        Home Assistant learns the values of the target the strip controls. Not before it is there: what is published
        before is lost, and the seed of the bridge (the watch of each number) publishes them then.
        """
        if self.ha is None or not self.ha.bridge.ready:
            return
        for part, number in self.ha.values.items():
            value: CommandValue | None = getattr(self.current, part)
            if value is not None and value.value is not None and value.value != number.current:
                number.set(value.value)

    def _commanded(self, part: str, payload: str) -> None:
        """Home Assistant sets the value of a part: as a hand does."""
        value: CommandValue | None = getattr(self.current, part)
        if value is None:
            return
        try:
            number = float(payload)
        except ValueError:
            _LOGGER.warning(f"{self.current.title}.{part}: Home Assistant sent {payload!r}, not a number")
            return
        value.set(number)

    @property
    def entities(self) -> dict[MQTTEntity, str | None]:
        return self.ha.entities if self.ha is not None else {}

    def _ha_ready(self) -> bool:
        return self.ha is not None and self.ha.bridge.ready

    # -- showing --------------------------------------------------------------------------------------------------

    @property
    def title(self) -> str:
        return self.look.label or super().title

    def update(self, state: AudioState) -> None:
        self.show()

    def show(self) -> None:
        target = self.target
        self.strip.set_text(0, self.look.label or (target.name if target is not None else self.identity.name))
        if self.absent:
            self.strip.set_color(Color.BLACK)
            self.strip.set_text(1, "off")
            self.strip.set_ring(0, RingMode.DOT)
            self.strip.park()
            for button in BUTTONS:
                self.strip.set_led(button, Led.OFF)
            return
        self.strip.set_color(self._color())
        self.strip.set_text(1, self.notice if self.notice is not None else self.lcd_text())
        self.strip.set_ring(*self._ring())
        self._show_fader()
        for button, name in BUTTONS.items():
            self.strip.set_led(button, self._led(button, self.config.button(name)))

    def _color(self) -> Color:
        color = self.config.color
        name: ColorName | None = None
        if color == HOME_ASSISTANT:
            entity = self.ha.color if self.ha is not None else None
            name = COLORS.get(entity.target_state or "") if entity is not None else None
        elif isinstance(color, WatchBinding):
            line = self.current.color
            name = self._colors.get(id(line)) if line is not None else None
        return color_of(name or self.look.color)

    def lcd_text(self) -> str:
        """The second line of the LCD: what `lcd` is bound to, else the value of the fader (or the encoder)."""
        lcd = self.config.lcd
        if lcd == HOME_ASSISTANT:
            entity = self.ha.bottom if self.ha is not None else None
            return (entity.target_state or "") if entity is not None else ""
        if isinstance(lcd, WatchBinding):
            line = self.current.lcd
            return (line.line or "") if line is not None else ""
        shown = self.current.run_value()
        if shown is not None:
            return shown.text()
        link = self.ha.fader or self.ha.encoder if self.ha is not None else None
        current = link.out.current if link is not None else None
        return f"{current:g}" if current is not None else ""

    def _ring(self) -> tuple[int, RingMode]:
        knob = self.current.knob()
        if knob is not None:
            return knob.ring()
        if self.ha is not None:
            link = self.ha.encoder or self.ha.fader
            if link is not None and (current := link.out.current) is not None:
                return ring_position(max(0.0, min(1.0, current / 100))), RingMode.WRAP
        return 0, RingMode.DOT

    def _show_fader(self) -> None:
        fader = self.current.fader
        if fader is not None:
            if not fader.touched and (fraction := fader.fraction()) is not None:
                self.strip.set_fader(fraction)
        elif self.ha is not None and self.ha.fader is not None:
            if self.ha.fader.out.current is not None:
                self.ha.fader.show()
        else:
            # nothing to set: down
            self.strip.set_fader(0.0)

    def _led(self, button: Button, setup: ButtonSetup) -> Led:
        led = setup.led
        if led == HOME_ASSISTANT:
            entity = self.ha.leds.get(button) if self.ha is not None else None
            return LEDS.get(entity.target_state or "", Led.OFF) if entity is not None else Led.OFF
        if isinstance(led, WatchBinding):
            line = self.current.leds.get(button)
            return led_of_line(line.line) if line is not None and line.line is not None else Led.OFF
        if led == "press":
            return Led.ON if self._press_lit(button, setup.press) else Led.OFF
        return Led.OFF

    def _press_lit(self, button: Button, action: Action) -> bool:
        """What the LED of a button shows for its press (`led = "press"`)."""
        actions = self.env.actions
        match action:
            case RunAction():
                return button in self._running
            case "next":
                return self.index != 0
            case "cycle_modes":
                return actions is not None and actions.mode != "default"
            case str() if action.startswith("mode:"):
                return actions is not None and actions.mode == action.removeprefix("mode:")
            case str() if action.startswith("toggle:"):
                return actions is not None and actions.value(action.removeprefix("toggle:"))
            case _:
                return False

    def held_meter(self, point: MeterPoint) -> Lit | None:
        """The level `meter` is bound to, over the LEDs of the meter; nothing while it is not known."""
        meter = self.config.meter
        level: float | None = None
        if self.absent:
            pass
        elif isinstance(meter, LevelBinding):
            line = self.current.meter
            if line is not None and line.line is not None:
                level = level_of_line(line.line, meter.min, meter.max)
        elif meter == HOME_ASSISTANT and self.ha is not None and self.ha.meter is not None:
            state = self.ha.meter.target_state
            try:
                level = max(0.0, min(100.0, float(state))) / 100 if state is not None else None
            except ValueError:
                level = None
        return Lit(round(level * METER_MAX)) if level is not None else None

    def notify(self, text: str) -> None:
        """Shows `text` on the second line for NOTICE_TIME."""
        self._end_notice_timer()
        self.notice = text
        self._notice_timer = asyncio.get_running_loop().call_later(NOTICE_TIME, self._end_notice)
        self.strip.set_text(1, text)

    def _end_notice(self) -> None:
        self._notice_timer = None
        self.notice = None
        self.show()

    def _end_notice_timer(self) -> None:
        if self._notice_timer is not None:
            self._notice_timer.cancel()
            self._notice_timer = None

    def _set_by_hand(self, value: CommandValue) -> None:
        """A hand changed a value: with `lcd` bound, it shows for a moment, as the balance does on audio strips."""
        if self.config.lcd is not None:
            self.notify(value.text())
        elif self.notice is not None:
            # the value is what changes now: it replaces the name of the target
            self._end_notice_timer()
            self.notice = None
            self.show()

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        if self.absent:
            return
        fader = self.current.fader
        if fader is not None:
            fader.moved(fraction)
            self._set_by_hand(fader)
        elif self.ha is not None and self.ha.fader is not None and self._ha_ready():
            self.ha.fader.moved(fraction)

    def on_touch(self, touched: bool) -> None:
        if self.absent and touched:
            return
        fader = self.current.fader
        if fader is not None:
            self._grip(fader if touched else None)
            # let go, it stays where the hand left it
            self._show_fader()
        elif self.ha is not None and self.ha.fader is not None:
            self.ha.fader.touch(touched)
            self.ha.event("fader_touched" if touched else "fader_released")

    def _grip(self, value: CommandValue | None) -> None:
        """Moves the finger of the fader to `value` (None: lets go)."""
        if self._gripped is not value:
            if self._gripped is not None:
                self._gripped.touch(False)
            if value is not None:
                value.touch(True)
            self._gripped = value

    def on_encoder(self, steps: int) -> None:
        if self.absent:
            return
        knob = self.current.knob()
        if knob is not None:
            knob.turn(steps)
            self._set_by_hand(knob)
            return
        if self.ha is None or not self._ha_ready():
            return
        if self.ha.encoder is not None:
            self.ha.encoder.turn(steps)
        elif self.ha.fader is not None and (current := self.ha.fader.out.current) is not None:
            # fine steps of the fader in Home Assistant
            value = round(max(0.0, min(100.0, current + steps * self.env.behavior.encoder_step / 10)), 1)
            self.ha.fader.out.set(value)
            self.strip.set_fader(value / 100)
            self.show()

    def on_encoder_press(self, pressed: bool) -> None:
        if self.absent:
            return
        knob = self.current.knob()
        if knob is not None:
            if pressed and knob.binding.push is not None:
                knob.push(pressed)
                self._set_by_hand(knob)
        elif self.ha is not None and self.ha.encoder is not None:
            self.ha.event("encoder_pressed" if pressed else "encoder_released")

    def on_button(self, button: Button, pressed: bool) -> None:
        name = BUTTONS.get(button)
        if name is None:
            return
        setup = self.config.button(name)
        if not setup.acts or (pressed and self.absent):
            return
        if pressed:
            if setup.hold == "off":
                self.act(button, setup.press, True)
            else:
                self._cancel_hold(button)
                self._holds[button] = asyncio.get_running_loop().call_later(HOLD_TIME, self._held, button, setup.hold)
            return
        timer = self._holds.pop(button, None)
        if timer is not None:
            # let go before the hold: a press
            timer.cancel()
            self.act(button, setup.press, True)
        if setup.press == HOME_ASSISTANT:
            # (the configuration gives it no hold: it was pressed at once)
            self.act(button, setup.press, False)

    def _cancel_hold(self, button: Button) -> None:
        timer = self._holds.pop(button, None)
        if timer is not None:
            timer.cancel()

    def _held(self, button: Button, action: Action) -> None:
        self._holds.pop(button, None)
        self.act(button, action, True)

    def act(self, button: Button, action: Action, down: bool) -> None:
        """Does an action of a button: once (`down`), or for `homeassistant` the press and the release."""
        actions = self.env.actions
        match action:
            case "off" | LaunchAction():
                # (a launch is refused by the configuration: a custom channel runs programs)
                pass
            case RunAction():
                self._run(button, action)
            case "next":
                self.switch()
            case "homeassistant":
                if self.ha is not None:
                    self.ha.event(f"{BUTTONS[button]}_{'pressed' if down else 'released'}")
            case str() if action == "cycle_modes" or action.startswith(("mode:", "toggle:")):
                if actions is None:
                    _LOGGER.warning(f"{self.identity.name}: {action} needs the slots")
                elif action == "cycle_modes":
                    actions.cycle_modes()
                elif action.startswith("mode:"):
                    actions.choose_mode(action.removeprefix("mode:"))
                else:
                    actions.toggle(action.removeprefix("toggle:"))
            case _:
                _LOGGER.debug(f"{self.identity.name}: a custom channel can't {action}")
        self.show()

    def _run(self, button: Button, action: RunAction) -> None:
        """
        Runs the program of a button, with `{value}` the value of the fader (or the encoder) and `{target}` the
        target; with `together` once per target. The LED of `led = "press"` is lit while it runs.
        """
        every = self.targets if self.config.together else [self.current]
        for programs in every:
            placeholders = {"target": programs.target.value} if programs.target is not None else {}
            if "value" in placeholders_of(action.run):
                value = programs.run_value()
                if value is None or value.value is None:
                    _LOGGER.warning(f"{programs.title}: {BUTTONS[button]}: no value yet, nothing runs")
                    continue
                placeholders["value"] = value_text(value.value)
            self._start_run(button, fill(action.run, **placeholders), f"{programs.title}.{BUTTONS[button]}")

    def _start_run(self, button: Button, argv: list[str], what: str) -> None:
        self._running[button] = self._running.get(button, 0) + 1

        async def run() -> None:
            try:
                await self.commands.run(argv)
            except CommandError as e:
                _LOGGER.warning(f"{what}: {e}")
            finally:
                # a run outlives its strip (a reload, an edit of the twin): the old strip shows nothing any more
                if not self._closed:
                    left = self._running.pop(button, 1) - 1
                    if left > 0:
                        self._running[button] = left
                    self.show()

        self.commands.start(run(), f"{what}: run")

    def close(self) -> None:
        self._grip(None)
        super().close()
        self._closed = True
        self._end_notice_timer()
        for timer in self._holds.values():
            timer.cancel()
        self._holds.clear()
        for thing in self._shared.values():
            thing.close()
        if self.ha is not None:
            self.ha.close()


def custom_strips(controllers: Mapping[str, StripController]) -> dict[str, CustomStrip]:
    """The custom strips among controllers by channel: the `ValueSource`s of `[controls]`."""
    return {name: controller for name, controller in controllers.items() if isinstance(controller, CustomStrip)}
