"""
What the bindings of entities of Home Assistant do on a strip (`config.bindings`): the state of an entity as the line a
part shows (`EntityLine`, like the `WatchedLine` of a `watch`), a value of an entity a fader or an encoder sets
(`EntityValue`, a `BoundValue` like the `CommandValue` of programs), and a service a button calls (`call_service()`).
They work with the connection of `Commands.hass`; without one (Simulate without `[homeassistant]`) the entities are not
known. `open_line()` and `open_value()` make the one a binding asks for, of programs or of an entity.
"""

import logging
from collections.abc import Callable, Mapping

from xtouch_daemon.config.bindings import (
    EntityBinding,
    EntityValueBinding,
    ServiceAction,
    ValueBinding,
    WatchBinding,
    fill_data,
)
from xtouch_daemon.homeassistant.client import HomeAssistantError
from xtouch_daemon.homeassistant.domains import domain_value
from xtouch_daemon.homeassistant.parts import LineKind, line_of, range_of, value_of
from xtouch_daemon.strips.value import BoundValue, CommandValue, WatchedLine
from xtouch_daemon.system.commands import Commands

_LOGGER = logging.getLogger(__name__)


class EntityLine:
    """
    The state of an entity as the line of a part of the kind (`homeassistant.parts.line_of()`), for as long as it lives
    (until `close()`). Its listeners are called when the line changed.
    """

    def __init__(self, binding: EntityBinding, commands: Commands, kind: LineKind):
        self.binding = binding
        self.kind: LineKind = kind
        self.source: tuple[object, ...] = ("entity", binding.entity, binding.attribute, kind)
        """What it shows the lines of: the same source, the same lines."""
        self.listeners: list[Callable[[], None]] = []
        self._hass = commands.hass
        self.line: str | None = self._line()
        """The line of the entity now; None while it is not known."""
        if self._hass is not None:
            self._hass.watch(binding.entity, self._changed)

    def _line(self) -> str | None:
        hass = self._hass
        if hass is None:
            return None
        return line_of(hass.state(self.binding.entity), self.binding.attribute, self.kind, hass.ever_synced)

    def _changed(self) -> None:
        line = self._line()
        if line != self.line:
            self.line = line
            for listener in list(self.listeners):
                listener()

    def close(self) -> None:
        if self._hass is not None:
            self._hass.unwatch(self.binding.entity, self._changed)


class EntityValue(BoundValue):
    """
    A value of an entity that a fader or an encoder sets (`EntityValueBinding`): it follows the entity, and a move
    calls the service of its domain (or its own `service`) with the newest value. Its range is the binding's, else the
    entity's, else the domain's. While the entity is not known, its value is not either (in Simulate it stays).
    """

    binding: EntityValueBinding

    def __init__(self, binding: EntityValueBinding, commands: Commands, encoder_step: int, what: str):
        self._hass = commands.hass
        self._failed = False
        """Whether the last call failed: the entity did not take the value."""
        state = self._hass.state(binding.entity) if self._hass is not None else None
        super().__init__(binding, commands, encoder_step, what, *range_of(state, binding))
        if self._hass is not None:
            self._hass.watch(binding.entity, self._entity_changed)
            self._entity_changed()

    def _entity_changed(self) -> None:
        assert self._hass is not None
        state = self._hass.state(self.binding.entity)
        if state is not None and (span := range_of(state, self.binding)) != (self.low, self.high):
            self.set_range(*span)
        value = value_of(state, self.binding)
        if value is not None or not self.commands.simulated:
            self._follow(value)

    def _settled(self) -> None:
        # after a call that failed, the fader goes back to where the entity is (after one that worked it stays: many
        # devices tell their new state a moment later, and the motor would jump back and forth)
        if self._failed:
            self._failed = False
            self._entity_changed()

    async def _apply(self, value: float) -> None:
        binding = self.binding
        domain = domain_value(binding.entity, binding.attribute)
        if binding.service is not None:
            service = binding.service
            data = fill_data(binding.data or {}, value)
        else:
            assert domain is not None, "a binding without a service has a domain with one (checked when loaded)"
            service = domain.service
            data = {domain.key: round(value) if domain.whole else value}
        try:
            await self.commands.call_service(service, data if isinstance(data, Mapping) else {}, binding.entity)
            self._failed = False
        except HomeAssistantError as e:
            self._failed = True
            _LOGGER.warning(f"{self.what}: {service} on {binding.entity}: {e}")

    def close(self) -> None:
        super().close()
        if self._hass is not None:
            self._hass.unwatch(self.binding.entity, self._entity_changed)


type Line = WatchedLine | EntityLine
"""The lines a part shows: of a `watch` or a `poll`, or of an entity."""


def open_line(
    part: WatchBinding | EntityBinding,
    commands: Commands,
    what: str,
    kind: LineKind,
    placeholders: Mapping[str, str] | None = None,
) -> Line:
    """The lines of a part bound to a `watch` or a `poll` (with `placeholders` filled in), or to an entity."""
    if isinstance(part, EntityBinding):
        return EntityLine(part, commands, kind)
    return WatchedLine(part.feed.filled(**(placeholders or {})), commands, what)


def line_source(part: WatchBinding | EntityBinding, kind: LineKind) -> tuple[object, ...]:
    """What the lines of a part come from (see `WatchedLine.source`, `EntityLine.source`)."""
    if isinstance(part, EntityBinding):
        return ("entity", part.entity, part.attribute, kind)
    return ("program", part.feed)


def open_value(
    binding: ValueBinding | EntityValueBinding,
    commands: Commands,
    encoder_step: int,
    what: str,
    placeholders: Mapping[str, str] | None = None,
) -> BoundValue:
    """The value a fader or an encoder sets: of programs of your own, or of an entity."""
    if isinstance(binding, EntityValueBinding):
        return EntityValue(binding, commands, encoder_step, what)
    return CommandValue(binding, commands, encoder_step, what, placeholders)


def call_service(commands: Commands, action: ServiceAction, what: str) -> None:
    """Calls the service of a press in a task of `commands`; a problem is logged as a warning, for `what`."""

    async def call() -> None:
        try:
            await commands.call_service(action.service, action.data, action.entity)
        except HomeAssistantError as e:
            _LOGGER.warning(f"{what}: {action.service}: {e}")

    commands.start(call(), f"{what}: {action.service}")
