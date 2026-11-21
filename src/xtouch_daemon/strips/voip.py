"""
The strip of a person of the voice chat, from the provider of `[voip]`: a `person` channel, or someone who shares the
`auto` slots (dark with their name while they are not there).
"""

from xtouch_daemon.audio.meter import Lit, Peak, Reading
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.values import MeterPoint, color_of
from xtouch_daemon.config.voip_strips import VoipStripConfig
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led
from xtouch_daemon.hardware.strip import Strip
from xtouch_daemon.strips.base import (
    Identity,
    Look,
    StripController,
    StripEnv,
    fader_position,
    fader_volume,
)
from xtouch_daemon.voip.provider import Capability, Participant, VoipProvider


class VoipStrip(StripController):
    """A person of the voice chat: the fader sets their volume, Mute mutes them."""

    def __init__(
        self,
        strip: Strip,
        env: StripEnv,
        identity: Identity,
        look: Look,
        provider: VoipProvider,
        config: VoipStripConfig,
    ):
        """`config` tells what the look doesn't: the color while talking, the volume range, `person`."""
        assert config.person, "a strip of the voice chat shows a person"
        super().__init__(strip, env, identity, look)
        self.provider = provider
        self.names = frozenset(name.casefold() for name in config.person)
        """The names of the person, ignoring case."""
        self.name = config.title
        """The top line: the label, else the first name."""
        self.talking_color = color_of(config.talking_color)
        self.max_volume = env.behavior.max_volume if config.max_volume is None else config.max_volume
        self._wanted: int | None = None
        """The volume the fader set last, shown until the provider reports one."""

    @property
    def participant(self) -> Participant | None:
        """The first participant with one of the names, in the order of the provider."""
        return next((each for each in self.provider.participants if each.name.casefold() in self.names), None)

    def can(self, capability: Capability) -> bool:
        """Whether the client of the participant can do `capability` (the provider, while they are not there)."""
        person = self.participant
        if person is None:
            return capability in self.provider.capabilities
        return capability in self.provider.capabilities_of(person.id)

    def update(self, state: AudioState) -> None:
        self.show()

    @property
    def title(self) -> str:
        return self.name

    def show(self) -> None:
        person = self.participant
        self.strip.set_led(Button.SELECT, Led.OFF)
        self.strip.set_led(Button.REC, Led.OFF)
        self.strip.set_led(Button.SOLO, Led.OFF)
        self.strip.set_ring(0)
        if person is None:
            # dark with the name, like a device that is not there
            self.strip.set_color(Color.BLACK)
            self.strip.set_text(0, self.name)
            self.strip.set_text(1, "away")
            self.strip.set_led(Button.MUTE, Led.OFF)
            self.strip.park()
            return
        self.strip.set_color(self.talking_color if person.talking else self.color)
        self.strip.set_text(0, self.name)
        self.strip.set_led(Button.MUTE, Led.ON if person.muted else Led.OFF)
        if self._wanted == person.volume:
            self._wanted = None
        volume = self._wanted if self._wanted is not None else person.volume
        if self.can(Capability.VOLUME):
            self.strip.set_fader(fader_position(volume, 0, self.max_volume, self.env.behavior.unity_at))
        else:
            self.strip.park()
        if person.muted:
            bottom = "muted"
        elif self.can(Capability.VOLUME):
            bottom = f"{volume}%"
        else:
            bottom = "talks" if person.talking else ""
        self.strip.set_text(1, bottom)

    def held_meter(self, point: MeterPoint) -> Reading | None:
        """
        The participant's level from the provider, before or after their volume; a full meter while they talk if
        the provider tells no level, or before the fader while they are muted (the voice chat doesn't get their
        voice then).
        """
        person = self.participant
        if not self.meter or person is None:
            return None
        talking = Lit(protocol.METER_MAX - 1) if person.talking else None
        if point == "pre_fader":
            if person.muted:
                return talking
            if person.pre_fader_level is not None:
                return Peak(person.pre_fader_level)
        if person.level is not None:
            return Peak(person.level)
        return talking

    # -- the device -----------------------------------------------------------------------------------------------

    def on_fader(self, fraction: float) -> None:
        person = self.participant
        if person is None or not self.can(Capability.VOLUME):
            return
        volume = round(fader_volume(fraction, 0, self.max_volume, self.env.behavior.unity_at))
        if volume == (self._wanted if self._wanted is not None else person.volume):
            return
        self._wanted = volume
        self.strip.set_text(1, f"{volume}%")
        self.run_command(self.provider.change_volume(person.id, volume), f"volume of {person.name}")

    def on_touch(self, touched: bool) -> None:
        if not touched:
            # back to where the participant's volume is (or goes)
            self.show()

    def on_button(self, button: Button, pressed: bool) -> None:
        if not pressed:
            return
        person = self.participant
        if button == Button.MUTE and person is not None and self.can(Capability.MUTE):
            self.run_command(self.provider.change_muted(person.id, not person.muted), f"mute {person.name}")
