"""
The whole configuration, and the checks across its sections (layout names, inheritance, strip counts).
"""

from typing import TYPE_CHECKING, Annotated

from pydantic import Field, PrivateAttr, model_validator

from xtouch_daemon.config.audio_strips import AutoStripConfig, DeviceStripConfig
from xtouch_daemon.config.base import Model
from xtouch_daemon.config.inheritance import Inheritance
from xtouch_daemon.config.layout import LayoutConfig
from xtouch_daemon.config.layout_strips import InheritStripConfig, VoipStripConfig
from xtouch_daemon.config.sections import BehaviorConfig, DeviceConfig, MqttConfig, SwitchingConfig, VoipConfig
from xtouch_daemon.config.strip import BaseStripConfig
from xtouch_daemon.config.strips import HomeAssistantStripConfig, StripConfig, collapses
from xtouch_daemon.config.values import DEFAULT_LAYOUT, MAX_STRIPS, Label, MeterPoint
from xtouch_daemon.hardware import protocol

if TYPE_CHECKING:
    from xtouch_daemon.config.slots import SlotsSetup


class Config(Model):
    device: DeviceConfig = DeviceConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    aliases: dict[str, Label] = {}  # noqa: RUF012 - a pydantic model, which copies the default
    """
    Names to show on `auto` strips for applications, at most 7 characters: for the name the sound server reports
    (`xtouch-daemon list-apps`), the label, e.g. "Discord" for "WEBRTC VoiceEngine".
    """
    strips: Annotated[tuple[StripConfig, ...], Field(alias="strip", max_length=MAX_STRIPS)] = ()
    """
    Up to 8 strips from the left; missing ones are `auto`. More with `collapse`: the device shows the first 8 that
    have something to control.
    """
    mqtt: MqttConfig | None = None
    """The MQTT broker, needed by `homeassistant` strips."""
    switching: SwitchingConfig = SwitchingConfig()
    voip: VoipConfig | None = None
    """The participants of the voice chat, for `voip` strips: without the section, they use its defaults (`bridge`)."""
    layouts: Annotated[tuple[LayoutConfig, ...], Field(alias="layout")] = ()
    """More sets of strips to switch to; the top-level strips are the layout `default`."""
    _slots: SlotsSetup | None = PrivateAttr(default=None)

    @property
    def slots(self) -> SlotsSetup | None:
        """
        The channels, states and slots of a file in that format (the prototype of
        docs/design/channels-states-slots.md), None for one with strips and layouts.
        """
        return self._slots

    @model_validator(mode="after")
    def _layouts(self) -> Config:
        names = [layout.name for layout in self.layouts]
        if DEFAULT_LAYOUT in names:
            raise ValueError(f"layout: {DEFAULT_LAYOUT} is the name of the top-level strips")
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"layouts with the same name: {', '.join(duplicates)}")
        for number, strip in enumerate(self.strips, start=1):
            if isinstance(strip, InheritStripConfig) and strip.layout is None and strip.strip is None:
                raise ValueError(
                    f"strip[{number}]: inherit of the default layout is only for the strips of a [[layout]] (or "
                    "name a strip or a layout)"
                )
        inheritance = Inheritance(self.layout_list())
        for index, layout in enumerate(self.layout_list()):
            strips = f"layout[{index}].strip" if index else "strip"
            for position in range(len(layout.strips)):
                inheritance.resolve((index, position))
            people = [
                name
                for strip in self.all_strips(layout.name)
                if isinstance(strip, VoipStripConfig)
                for name in {name.casefold() for name in strip.person}
            ]
            twice = sorted({name for name in people if people.count(name) > 1})
            if twice:
                where = "" if index == 0 else f" (layout {layout.name})"
                raise ValueError(f"voip strips with the same person{where}: {', '.join(twice)}")
            never = self.unreachable(layout.name)
            if never:
                numbers = ", ".join(f"{strips}[{number}]" for number in never)
                raise ValueError(
                    f"{numbers} can never show: {protocol.STRIPS} strips before them don't collapse "
                    "(`collapse = true` on some of them, or fewer strips)"
                )
        return self

    @model_validator(mode="after")
    def _volume_ranges(self) -> Config:
        for index, layout in enumerate(self.layout_list()):
            for number, strip in enumerate(layout.strips, start=1):
                if not isinstance(strip, BaseStripConfig):
                    continue
                for where, bottom, top in strip.volume_ranges(self.behavior):
                    if bottom >= top:
                        place = (f"layout[{index}]." if index else "") + f"strip[{number}]"
                        place += f".{where}" if where else ""
                        raise ValueError(f"{place}: min_volume ({bottom}) is not below max_volume ({top})")
        return self

    @model_validator(mode="after")
    def _home_assistant_strips(self) -> Config:
        for layout in self.layout_list():
            if self.home_assistant_strips(layout.name) and self.mqtt is None:
                raise ValueError("strips in Home Assistant need an [mqtt] section")
            ids = [strip_id for _, strip_id in self.entity_strips(layout.name)]
            duplicates = sorted({strip_id for strip_id in ids if ids.count(strip_id) > 1})
            if duplicates:
                where = "" if layout.name == DEFAULT_LAYOUT else f" (layout {layout.name})"
                raise ValueError(f"strips in Home Assistant with the same id{where}: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def _voip_strips(self) -> Config:
        strips = (strip for layout in self.layout_list() for strip in layout.strips)
        if self.voip is None and any(isinstance(strip, VoipStripConfig) for strip in strips):
            # the section has defaults for everything: voip strips don't need it written out
            return self.model_copy(update={"voip": VoipConfig()})
        return self

    def layout_list(self) -> tuple[LayoutConfig, ...]:
        """Every layout, the default one (the top-level strips) first."""
        return (LayoutConfig.model_construct(name=DEFAULT_LAYOUT, label="Default", strips=self.strips), *self.layouts)

    @property
    def layout_names(self) -> tuple[str, ...]:
        return tuple(layout.name for layout in self.layout_list())

    def layout(self, name: str) -> LayoutConfig:
        """The layout of the name (KeyError for none)."""
        for layout in self.layout_list():
            if layout.name == name:
                return layout
        raise KeyError(name)

    def meter_point(self, strip: StripConfig, layout: str = DEFAULT_LAYOUT) -> MeterPoint:
        """
        Where the meter of a strip of `all_strips(layout)` takes the level: its own `meter_point`, else the layout's,
        else `behavior.meter_point`. An `inherit` strip brings its own along, the layout is the one it is shown in.
        """
        if isinstance(strip, BaseStripConfig) and strip.meter_point is not None:
            return strip.meter_point
        return self.layout(layout).meter_point or self.behavior.meter_point

    def all_strips(self, layout: str = DEFAULT_LAYOUT) -> tuple[StripConfig, ...]:
        """
        The configuration of every strip of a layout, at least the 8 of the device: `inherit` ones are the strips
        they refer to, and the ones that are not configured are `auto`.
        """
        index = self.layout_names.index(self.layout(layout).name)
        inheritance = Inheritance(self.layout_list())
        result = [inheritance.resolve((index, position)) for position in range(len(self.layout(layout).strips))]
        return (*result, *(AutoStripConfig(type="auto") for _ in range(protocol.STRIPS - len(result))))

    def inherited(self, layout: str = DEFAULT_LAYOUT) -> tuple[str | None, ...]:
        """
        For each strip of `all_strips()`, where it comes from if it is an `inherit` strip (e.g.
        "layout voice, strip 2"), None for the others.
        """
        index = self.layout_names.index(self.layout(layout).name)
        inheritance = Inheritance(self.layout_list())
        result: list[str | None] = []
        for position, strip in enumerate(self.layout(layout).strips):
            where: str | None = None
            if isinstance(strip, InheritStripConfig):
                origin = inheritance.origin((index, position))
                name = self.layout_names[origin[0]] if origin is not None else strip.layout or DEFAULT_LAYOUT
                where = ("the default layout" if name == DEFAULT_LAYOUT else f"layout {name}") + (
                    f", strip {origin[1] + 1}" if origin is not None else ", an auto strip"
                )
            result.append(where)
        return (*result, *[None] * (len(self.all_strips(layout)) - len(result)))

    def unreachable(self, layout: str = DEFAULT_LAYOUT) -> list[int]:
        """
        The strips of the layout (their numbers in its list, from 1) that can never get a fader: 8 strips without
        `collapse` come before them.
        """
        steady = 0
        never: list[int] = []
        for number, strip in enumerate(self.all_strips(layout), start=1):
            if steady >= protocol.STRIPS:
                never.append(number)
            if not collapses(strip):
                steady += 1
        return never

    def entity_strips(self, layout: str = DEFAULT_LAYOUT) -> list[tuple[StripConfig, str]]:
        """
        The strips of a layout with entities in Home Assistant, with their ids: those of `home_assistant_strips()`,
        and with [mqtt] the ones with `choices` (a select of the choice).
        """
        return [
            (strip, strip.id or f"strip_{number}")
            for number, strip in enumerate(self.all_strips(layout), start=1)
            if isinstance(strip, HomeAssistantStripConfig)
            or (isinstance(strip, BaseStripConfig) and strip.uses_home_assistant)
            or (self.mqtt is not None and isinstance(strip, DeviceStripConfig) and strip.switches)
        ]

    def home_assistant_strips(self, layout: str = DEFAULT_LAYOUT) -> list[tuple[StripConfig, str]]:
        """
        The strips of a layout with entities in Home Assistant (`homeassistant` ones, and a fader or encoder), with
        their ids.
        """
        return [
            (strip, strip.id or f"strip_{number}")
            for number, strip in enumerate(self.all_strips(layout), start=1)
            if isinstance(strip, HomeAssistantStripConfig)
            or (isinstance(strip, BaseStripConfig) and strip.uses_home_assistant)
        ]
