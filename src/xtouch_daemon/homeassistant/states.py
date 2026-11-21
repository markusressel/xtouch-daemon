"""
The states of the entities of Home Assistant, as `subscribe_entities` of its WebSocket API sends them: compressed, a
message with all of them (`"a"`, added), then changes (`"c"`, with `"+"` what is new and `"-"` the attributes that
went) and removals (`"r"`). `get_states` sends them uncompressed (`from_state()`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from xtouch_daemon.homeassistant.domains import UNKNOWN_STATES


@dataclass(frozen=True)
class EntityState:
    """An entity of Home Assistant: its state, and its attributes."""

    entity_id: str
    state: str
    attributes: Mapping[str, Any] = field(default_factory=dict[str, Any])

    @property
    def known(self) -> bool:
        """Whether Home Assistant knows its state: not `unavailable` or `unknown`."""
        return self.state not in UNKNOWN_STATES

    @property
    def name(self) -> str:
        """What Home Assistant calls it: its `friendly_name`, else its id."""
        name = self.attributes.get("friendly_name")
        return name if isinstance(name, str) and name else self.entity_id


def from_state(data: Mapping[str, Any]) -> EntityState:
    """An entity as `get_states` and events send it: `entity_id`, `state`, `attributes`."""
    return EntityState(str(data["entity_id"]), str(data.get("state", "")), dict(data.get("attributes") or {}))


def _compressed(entity_id: str, data: Mapping[str, Any]) -> EntityState:
    return EntityState(entity_id, str(data.get("s", "")), dict(data.get("a") or {}))


def apply_event(states: dict[str, EntityState], event: Mapping[str, Any]) -> set[str]:
    """
    Applies an event of `subscribe_entities` to `states` (by entity id); the ids of the entities that changed. A
    change of an entity that is not there (it never came) is ignored.
    """
    changed: set[str] = set()
    added = cast(Mapping[str, Mapping[str, Any]], event.get("a") or {})
    for entity_id, data in added.items():
        states[entity_id] = _compressed(entity_id, data)
        changed.add(entity_id)
    changes = cast(Mapping[str, Mapping[str, Any]], event.get("c") or {})
    for entity_id, diff in changes.items():
        old = states.get(entity_id)
        if old is None:
            continue
        attributes = dict(old.attributes)
        state = old.state
        plus = cast(Mapping[str, Any], diff.get("+") or {})
        if "s" in plus:
            state = str(plus["s"])
        attributes.update(cast(Mapping[str, Any], plus.get("a") or {}))
        minus = cast(Mapping[str, Any], diff.get("-") or {})
        for name in minus.get("a") or ():
            attributes.pop(name, None)
        states[entity_id] = EntityState(entity_id, state, attributes)
        changed.add(entity_id)
    for entity_id in cast(list[str], event.get("r") or []):
        if states.pop(entity_id, None) is not None:
            changed.add(entity_id)
    return changed
