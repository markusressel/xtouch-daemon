"""
What the daemon knows of the domains of Home Assistant: which value of an entity a fader or an encoder sets by default,
its range, and the service that sets it (`DOMAIN_VALUES`). Other domains need a `service` of their own.
"""

import re
from dataclasses import dataclass

ENTITY_ID = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
"""An entity id: `<domain>.<object id>`, e.g. `sensor.cpu_temp`."""
SERVICE = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
"""A service: `<domain>.<service>`, e.g. `light.toggle`."""
UNKNOWN_STATES = frozenset({"unavailable", "unknown"})
"""The states of an entity Home Assistant does not know the state of."""


def domain_of(entity_id: str) -> str:
    """The domain of an entity id, e.g. `light` of `light.desk`."""
    return entity_id.partition(".")[0]


@dataclass(frozen=True)
class DomainValue:
    """The value of the entities of a domain that a fader or an encoder sets, and how a service sets it."""

    attribute: str | None
    """The attribute with the value, None for the state."""
    min: float
    max: float
    service: str
    """The service that sets it, e.g. `light.turn_on`."""
    key: str
    """The key of the value in the data of the service, e.g. `brightness`."""
    whole: bool = False
    """The service takes whole numbers only."""
    off_is_min: bool = False
    """An entity that is `off` has the value `min` (a light without brightness then)."""
    ranged: bool = False
    """The entity tells its range in its attributes `min` and `max` (a `number`)."""


DOMAIN_VALUES: dict[str, DomainValue] = {
    "number": DomainValue(None, 0, 100, "number.set_value", "value", ranged=True),
    "input_number": DomainValue(None, 0, 100, "input_number.set_value", "value", ranged=True),
    "light": DomainValue("brightness", 0, 255, "light.turn_on", "brightness", whole=True, off_is_min=True),
    "media_player": DomainValue("volume_level", 0, 1, "media_player.volume_set", "volume_level"),
    "cover": DomainValue("current_position", 0, 100, "cover.set_cover_position", "position", whole=True),
    "fan": DomainValue("percentage", 0, 100, "fan.set_percentage", "percentage", whole=True, off_is_min=True),
}
"""The domains whose value a fader or an encoder sets without a `service`, by domain."""


def domain_value(entity_id: str, attribute: str | None) -> DomainValue | None:
    """
    The value of the domain of an entity, if the binding sets that one: without an attribute, or with the domain's
    own (e.g. `brightness` of a light). None for another attribute, or a domain without a value.
    """
    value = DOMAIN_VALUES.get(domain_of(entity_id))
    if value is None or attribute not in (None, value.attribute):
        return None
    return value
