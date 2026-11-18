"""A strip for an output or an input device, or for the default one."""

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from haad_mqtt_autodiscovery.entity import MQTTEntity
from haad_mqtt_autodiscovery.entity.select import MQTTSelect

from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.audio.model import AudioState, Card, Device, Direction
from xtouch_daemon.config.audio_strips import ChoiceConfig, ProfileConfig
from xtouch_daemon.config.values import EncoderMode
from xtouch_daemon.hardware.protocol import LCD_CELL_WIDTH, Button, Led
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips.base import Identity, Level, Look, StripEnv, VolumeStrip

if TYPE_CHECKING:
    from xtouch_daemon.strips.homeassistant import HomeAssistantControls

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Switch:
    """A switch of the sound card to a profile, until the card is in it."""

    card: str
    profile: str
    """The name of the profile."""
    config: ProfileConfig
    make_default: bool
    """Whether the device of the profile becomes the default (the old one was)."""


class DeviceStrip(VolumeStrip):
    """
    The volume of a device (`devices` holds its node name or description), or of the default device without
    `devices`, which follows when the default changes. With `select`, the select button makes the device the default,
    and its LED is on while it is. A device that is not there (e.g. headphones that are switched off) shows "off" on a
    dark LCD.

    With several devices (or wildcards, e.g. every pair of Bluetooth headphones) the strip shows one of those that are
    there: the default one, or else the one it showed last (or the first). Select makes it the default; on the default
    one, it switches to the next one and makes that the default.

    With `profiles`, the rec button switches the sound card of the device to the next of them (e.g. from analog to
    digital output), and its LED is on for every profile but the first. The label of the profile is the label of the
    strip (e.g. "Phones" for the analog output, "Speaker" for the digital one), from the press on. The devices of the
    card change with it: if the old one was the default, the new one becomes the default. A profile may have a volume
    range of its own (e.g. up to 200 % for weak speakers).
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        direction: Direction,
        devices: tuple[str, ...],
        look: Look,
        select: bool = True,
        profiles: tuple[ProfileConfig, ...] = (),
        min_volume: int | None = None,
        max_volume: int | None = None,
        encoder: EncoderMode = "volume",
        controls: HomeAssistantControls | None = None,
    ):
        super().__init__(strip, env, identity, look, min_volume, max_volume, encoder, controls)
        self.label = look.label or ("Output" if direction == Direction.OUTPUT else "Input")
        self.direction = direction
        self.devices = devices
        self.select = select and bool(devices)
        self.device: Device | None = None
        self.candidates: tuple[Device, ...] = ()
        """The devices of `devices` that are there."""
        self._label_option = look.label
        self.default = False
        """Whether the device shown is the default one."""
        self.profiles = profiles
        if profiles:
            # its LED shows the profile
            self.own_leds = frozenset({Button.REC})
        self.card: Card | None = None
        """The sound card of the device shown."""
        self._switch: _Switch | None = None

    def _shown(self, state: AudioState) -> Device | None:
        if not self.devices:
            return state.device(self.direction, None)
        candidates = state.devices_matching(self.direction, self.devices)
        default = next((device for device in candidates if state.is_default(device)), None)
        last = next((device for device in candidates if self.device and device.name == self.device.name), None)
        return default or last or next(iter(candidates), None)

    def current(self, state: AudioState) -> tuple[Level | None, bool]:
        self.device = self._shown(state)
        self.candidates = state.devices_matching(self.direction, self.devices)
        self.card = state.card(self.device.card) if self.device is not None else None
        self._update_label()
        if self.device is None:
            return None, False
        return Level(self.device.volume, self.device.muted, self.device.balance), True

    def update(self, state: AudioState) -> None:
        super().update(state)
        self.default = self.is_default(state)
        self.strip.set_led(Button.SELECT, Led.ON if self.select and self.default else Led.OFF)
        if self.profiles:
            self.strip.set_led(Button.REC, Led.ON if self.profile_index() not in (None, 0) else Led.OFF)
        switch = self._switch
        # the device of the profile switched to is there
        if self.card is not None and self.device is not None and switch is not None:
            if (self.card.name, self.card.profile) != (switch.card, switch.profile):
                return
            self._switch = None
            if switch.make_default and not self.default:
                self.run_command(self.env.backend.set_default(self.direction, self.device.name), "make default")

    def set_look(self, look: Look) -> None:
        super().set_look(look)
        self._label_option = look.label

    def _update_label(self) -> None:
        """The label of the profile, else the configured one, else the start of the description of the device."""
        if (profile := self._profile()) is not None:
            self.label = profile.label
        elif self._label_option is not None:
            self.label = self._label_option
        elif self.devices and self.device is not None:
            self.label = self.device.description[:LCD_CELL_WIDTH]

    def volume_range(self) -> tuple[int, int]:
        bottom, top = super().volume_range()
        if (profile := self._profile()) is None:
            return bottom, top
        return (
            bottom if profile.min_volume is None else profile.min_volume,
            top if profile.max_volume is None else profile.max_volume,
        )

    def _profile(self) -> ProfileConfig | None:
        """The profile the card is in (or switches to), None for another one."""
        if self._switch is not None:
            return self._switch.config
        index = self.profile_index()
        return None if index is None else self.profiles[index]

    def profile_index(self) -> int | None:
        """Which of `profiles` the card of the device is in, None for another one (or without a card)."""
        if self.card is None:
            return None
        active = self.card.profile_named(self.card.profile)
        return next(
            (i for i, profile in enumerate(self.profiles) if active is not None and active.matches(profile.profile)),
            None,
        )

    def recording(self, state: AudioState) -> bool:
        return self.device is not None and state.is_recorded(self.device)

    @property
    def title(self) -> str:
        return self.label

    def playing(self, state: AudioState) -> bool:
        return self.device is not None and self.device.running

    def is_default(self, state: AudioState) -> bool:
        return self.device is not None and state.is_default(self.device)

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        device = self._shown(state)
        if not self.meter or device is None:
            return set()
        return {CaptureTarget(device.name, monitor=self.direction == Direction.OUTPUT)}

    def is_playing(self, target: CaptureTarget, state: AudioState) -> bool:
        device = state.device(self.direction, target.node)
        return device is not None and device.running

    def target_gain(self, target: CaptureTarget, state: AudioState) -> float | None:
        device = state.device(self.direction, target.node)
        return None if device is None else device.gain

    def on_button(self, button: Button, pressed: bool) -> None:
        super().on_button(button, pressed)
        if pressed and button == Button.REC and self.profiles:
            self._switch_profile()
        if not (pressed and button == Button.SELECT and self.select and self.device is not None):
            return
        target = self.device
        if self.default and len(self.candidates) > 1:
            # the next one of them
            target = self.candidates[(self.candidates.index(target) + 1) % len(self.candidates)]
        self.run_command(self.env.backend.set_default(self.direction, target.name), "make default")

    def _switch_profile(self) -> None:
        card = self.card
        if card is None:
            return
        index = self.profile_index()
        wanted = self.profiles[0 if index is None else (index + 1) % len(self.profiles)]
        profile = card.profile_named(wanted.profile)
        if profile is None:
            _LOGGER.warning(f"{self.identity.name}: {card.name} has no profile {wanted.profile!r}")
            return
        self._switch = _Switch(card.name, profile.name, wanted, make_default=self.default)
        self.label = wanted.label
        self.show()
        self.run_command(self._set_profile(self._switch), f"switch to {wanted.label}")

    async def _set_profile(self, switch: _Switch) -> None:
        try:
            await self.env.backend.set_card_profile(switch.card, switch.profile)
        except AudioCommandError:
            if self._switch is switch:
                self._switch = None
                # back to the label of the profile the card is still in
                self._update_label()
                self.show()
            raise

    async def apply_volume(self, percent: int) -> None:
        if self.device is not None:
            await self.env.backend.set_device_volume(self.direction, self.device.name, percent)

    async def apply_mute(self, muted: bool) -> None:
        if self.device is not None:
            await self.env.backend.set_device_mute(self.direction, self.device.name, muted)

    async def apply_balance(self, balance: float) -> None:
        if self.device is not None:
            await self.env.backend.set_device_balance(self.direction, self.device.name, balance)


@dataclass(frozen=True)
class _Choosing:
    """A press of Select on a strip with choices: the choice it goes to, until its device is the default."""

    choice: int
    """Which of the choices, from 0."""
    previous: int | None
    """The choice shown before, to go back to if the switch fails."""
    card: str | None = None
    """The card that switches to `profile` first (by name), None once it is in it, or for a choice without one."""
    profile: str | None = None
    """The name of the profile."""
    defaulted: bool = False
    """Whether the device of the choice was made the default."""


class ChoiceStrip(DeviceStrip):
    """
    One of several devices (`choices`), each maybe in a profile of its sound card: e.g. headphones on the analog
    output and speakers on the digital one of the same card, and Bluetooth headphones. The strip shows the choice
    whose device is the default, or else the one it showed last, or else the first one there is. Select goes to the
    next choice there is (one whose device is there, or whose card has its profile): it switches the card to the
    profile first, if it is in another one, and then makes the device the default. The label shows the choice at
    once; a switch that fails goes back. A press while a switch is on its way goes on from where it goes.

    With [mqtt], `select.<ns>_<id>_output` (or `_input`) in Home Assistant chooses too.
    """

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        direction: Direction,
        choices: tuple[ChoiceConfig, ...],
        look: Look,
        min_volume: int | None = None,
        max_volume: int | None = None,
        encoder: EncoderMode = "volume",
        controls: HomeAssistantControls | None = None,
    ):
        """With a bridge, the choice is an entity in Home Assistant too."""
        super().__init__(
            strip,
            env,
            identity,
            direction,
            (),
            look,
            min_volume=min_volume,
            max_volume=max_volume,
            encoder=encoder,
            controls=controls,
        )
        self.select = True
        self.choices = choices
        self.options = _options(choices)
        """The names of the choices in Home Assistant: their labels (or devices), made unique."""
        self.choice: int | None = None
        """The choice shown, from 0; None while none is there."""
        self.available: tuple[int, ...] = ()
        """The choices that are there."""
        self._devices: dict[int, Device] = {}
        """The device of each choice that is there."""
        self._choosing: _Choosing | None = None
        self._state = AudioState()
        self.ha_select: MQTTSelect | None = None
        if env.bridge is not None:
            self.ha_select = MQTTSelect(
                env.bridge.config.namespace,
                f"{identity.id}_{direction.value}",
                f"{identity.name} {direction.value}",
                options=list(self.options),
                icon="mdi:speaker" if direction == Direction.OUTPUT else "mdi:microphone",
                device=env.bridge.device,
            )
            env.bridge.watch(self.ha_select, lambda _: self._publish_choice())
            env.bridge.watch_commands(self.ha_select, self._chosen_in_home_assistant)

    # -- which choice -----------------------------------------------------------------------------------------------

    def _device_of(self, state: AudioState, choice: ChoiceConfig) -> Device | None:
        return next(iter(state.devices_matching(self.direction, (choice.device,))), None)

    def _has_profile(self, state: AudioState, choice: ChoiceConfig) -> bool:
        """Whether the card of the choice is there and has its profile (its device comes with a switch)."""
        if choice.card is None or choice.profile is None:
            return False
        card = state.card_matching(choice.card)
        return card is not None and card.profile_named(choice.profile) is not None

    def _active(self, state: AudioState) -> int | None:
        if self._choosing is not None:
            return self._choosing.choice
        defaults = [index for index, device in self._devices.items() if state.is_default(device)]
        if defaults:
            return self.choice if self.choice in defaults else defaults[0]
        if self.choice in self.available:
            return self.choice
        return next(iter(self.available), None)

    def current(self, state: AudioState) -> tuple[Level | None, bool]:
        self._state = state
        self._devices = {}
        for index, choice in enumerate(self.choices):
            device = self._device_of(state, choice)
            if device is not None:
                self._devices[index] = device
        self.available = tuple(
            index
            for index, choice in enumerate(self.choices)
            if index in self._devices or self._has_profile(state, choice)
        )
        self._follow_switch(state)
        self.choice = self._active(state)
        self.device = self._devices.get(self.choice) if self.choice is not None else None
        self.candidates = tuple(self._devices.values())
        self.card = None
        self._update_label()
        self._publish_choice()
        if self.device is None:
            return None, False
        return Level(self.device.volume, self.device.muted, self.device.balance), True

    def _follow_switch(self, state: AudioState) -> None:
        """Carries a switch on: the profile first, then the default, until the device is the default."""
        choosing = self._choosing
        if choosing is None:
            return
        if choosing.card is not None:
            card = state.card(choosing.card)
            if card is None:
                _LOGGER.warning(f"{self.identity.name}: {choosing.card} went away during the switch")
                self._choosing = None
                return
            if card.profile != choosing.profile:
                return
            choosing = self._choosing = replace(choosing, card=None, profile=None)
        device = self._devices.get(choosing.choice)
        if device is None:
            # the device of the profile is not there yet
            return
        if state.is_default(device):
            self._choosing = None
        elif not choosing.defaulted:
            self._choosing = replace(choosing, defaulted=True)
            self.run_command(self._make_default(self._choosing, device.name), "make default")

    def _choice_config(self) -> ChoiceConfig | None:
        return self.choices[self.choice] if self.choice is not None else None

    def _update_label(self) -> None:
        """The label of the choice, else the configured one, else the start of the description of its device."""
        choice = self._choice_config()
        if choice is not None and choice.label is not None:
            self.label = choice.label
        elif self._label_option is not None:
            self.label = self._label_option
        elif self.device is not None:
            self.label = self.device.description[:LCD_CELL_WIDTH]
        elif choice is not None:
            self.label = choice.device[:LCD_CELL_WIDTH]

    def volume_range(self) -> tuple[int, int]:
        bottom, top = VolumeStrip.volume_range(self)
        choice = self._choice_config()
        if choice is None:
            return bottom, top
        return (
            bottom if choice.min_volume is None else choice.min_volume,
            top if choice.max_volume is None else choice.max_volume,
        )

    def meter_targets(self, state: AudioState) -> set[CaptureTarget]:
        if not self.meter or self.device is None:
            return set()
        return {CaptureTarget(self.device.name, monitor=self.direction == Direction.OUTPUT)}

    # -- switching --------------------------------------------------------------------------------------------------

    def on_button(self, button: Button, pressed: bool) -> None:
        VolumeStrip.on_button(self, button, pressed)
        if not (pressed and button == Button.SELECT) or not self.available:
            return
        if self._choosing is None and self.choice in self._devices and not self.default:
            # the one shown, which is not the default: it becomes the default
            self.choose(self.choice)
            return
        base = self._choosing.choice if self._choosing is not None else self.choice
        after = [index for index in self.available if base is None or index > base]
        self.choose((after or list(self.available))[0])

    def choose(self, index: int) -> None:
        """Switches to the choice: its profile first, if its card is in another one, then the default."""
        state = self._state
        choice = self.choices[index]
        device = self._devices.get(index)
        card = state.card_matching(choice.card) if choice.card is not None else None
        profile = card.profile_named(choice.profile) if card is not None and choice.profile is not None else None
        if card is not None and profile is not None and card.profile != profile.name:
            choosing = _Choosing(index, self.choice, card.name, profile.name)
            self._choosing = choosing
            self.run_command(self._set_choice_profile(choosing, card.name, profile.name), f"switch to {choice.title}")
        elif device is not None:
            choosing = _Choosing(index, self.choice, defaulted=True)
            self._choosing = choosing
            self.run_command(self._make_default(choosing, device.name), "make default")
        else:
            _LOGGER.warning(f"{self.identity.name}: {choice.title} is not there")
            return
        _LOGGER.info(f"{self.identity.name}: switching to {choice.title}")
        # the label of the choice at once, the sound server follows
        self.update(state)

    async def _set_choice_profile(self, choosing: _Choosing, card: str, profile: str) -> None:
        try:
            await self.env.backend.set_card_profile(card, profile)
        except AudioCommandError:
            self._failed(choosing)
            raise

    async def _make_default(self, choosing: _Choosing, device: str) -> None:
        try:
            await self.env.backend.set_default(self.direction, device)
        except AudioCommandError:
            self._failed(choosing)
            raise
        if self._choosing is choosing:
            # the sound server reports it with the next state; until then the choice shown stays
            self._choosing = None

    def _failed(self, choosing: _Choosing) -> None:
        """Back to what the sound server says, unless another press came in the meantime."""
        if self._choosing is choosing:
            self._choosing = None
            self.choice = choosing.previous
            self.update(self._state)

    # -- Home Assistant ---------------------------------------------------------------------------------------------

    @property
    def entities(self) -> dict[MQTTEntity, str | None]:
        entities = super().entities
        if self.ha_select is not None:
            entities[self.ha_select] = self.options[self.choice or 0]
        return entities

    def _chosen_in_home_assistant(self, option: str) -> None:
        if option not in self.options:
            return
        index = self.options.index(option)
        if index == self.choice and self._choosing is None:
            # already there; the state goes back to it
            self._publish_choice()
        elif index in self.available:
            self.choose(index)
        else:
            _LOGGER.warning(f"{self.identity.name}: {self.choices[index].title} is not there")
            self._publish_choice()

    def _publish_choice(self) -> None:
        """Home Assistant shows the choice of the strip: a state that says otherwise is put right."""
        select = self.ha_select
        bridge = self.env.bridge
        if select is None or bridge is None or not bridge.ready or self.choice is None:
            return
        option = self.options[self.choice]
        if select.target_state != option:
            self.run_command(select.set_state(option), "mqtt choice")

    def close(self) -> None:
        super().close()
        if self.ha_select is not None and self.env.bridge is not None:
            self.env.bridge.unwatch(self.ha_select)


def _options(choices: tuple[ChoiceConfig, ...]) -> tuple[str, ...]:
    """The titles of the choices, the second and later of the same title with a number: options must differ."""
    options: list[str] = []
    for choice in choices:
        option, number = choice.title, 1
        while option in options:
            number += 1
            option = f"{choice.title} {number}"
        options.append(option)
    return tuple(options)
