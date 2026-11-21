"""
The entities of Home Assistant for the GUI (`[homeassistant]`): the suggestions of a field of an entity or an
attribute, what an unset option of an entity binding does by the domain of its entity, how the daemon's connection to
the API is doing (from its live view), and a test of the settings in the editor. The errors are put in words that say
what to check.
"""

import json
import tomllib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import tomlkit
from pydantic import ValidationError

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.homeassistant.client import Fetched, HomeAssistantError
from xtouch_daemon.homeassistant.domains import DOMAIN_VALUES, ENTITY_ID, domain_of
from xtouch_daemon.homeassistant.states import EntityState
from xtouch_daemon.live.messages import HomeAssistantState, Snapshot

type Fetch = Callable[[HomeAssistantConfig], Awaitable[Fetched]]
"""Connects once with the settings: the version of Home Assistant and its entities (see `client.fetch`)."""

RETRY = "The daemon tries again, waiting longer each time."
TOKEN_HINT = "Create a long-lived access token in your profile in Home Assistant, on the Security tab."

DOMAIN_ICONS = {
    "automation": "robot",
    "binary_sensor": "checkbox-blank-circle-outline",
    "button": "gesture-tap-button",
    "climate": "thermostat",
    "cover": "window-shutter",
    "device_tracker": "map-marker",
    "fan": "fan",
    "input_boolean": "toggle-switch-outline",
    "input_number": "ray-vertex",
    "input_select": "format-list-bulleted",
    "input_text": "form-textbox",
    "light": "lightbulb",
    "lock": "lock",
    "media_player": "cast",
    "number": "ray-vertex",
    "person": "account",
    "scene": "palette",
    "script": "script-text",
    "select": "format-list-bulleted",
    "sensor": "eye",
    "sun": "white-balance-sunny",
    "switch": "toggle-switch",
    "text": "form-textbox",
    "update": "package-up",
    "vacuum": "robot-vacuum",
    "weather": "weather-partly-cloudy",
    "zone": "map-marker-radius",
}
"""The icon of the entities of a domain (Material Design, as Home Assistant has them)."""
DEFAULT_ICON = "shape"
"""The icon of an entity of another domain."""


def domain_icon(entity_id: str) -> str:
    """The icon of an entity by its domain, e.g. `lightbulb` for `light.desk`."""
    return DOMAIN_ICONS.get(domain_of(entity_id), DEFAULT_ICON)


def section_config(section: object) -> HomeAssistantConfig | str | None:
    """
    The settings of `[homeassistant]` in the editor: None without the section, else the settings, or why they can't
    be used yet.
    """
    if section is None:
        return None
    try:
        return HomeAssistantConfig.model_validate(section)
    except ValidationError as e:
        problem = e.errors()[0]
        where = ".".join(map(str, problem["loc"]))
        message = str(problem["msg"]).removeprefix("Value error, ")
        return f"{where}: {message}" if where else message


def data_text(value: object) -> str:
    """The data of a service as it is typed, an inline table of TOML: `{ brightness_pct = 50 }`."""
    if isinstance(value, Mapping):
        table = tomlkit.inline_table()
        table.update(value)  # pyright: ignore[reportUnknownMemberType]
        return table.as_string().strip()
    return "" if value is None else str(value)


def parse_data(text: str) -> dict[str, Any] | str | None:
    """
    Typed data of a service: the table, None for nothing, or the text as it is when it is no inline table (its
    problem then says so).
    """
    text = text.strip()
    if not text:
        return None
    try:
        value = tomllib.loads(f"data = {text}")["data"]
    except tomllib.TOMLDecodeError:
        return text
    return value if isinstance(value, dict) else text


# -- suggestions --------------------------------------------------------------------------------------------------


def state_text(entity: EntityState) -> str:
    """The state of an entity for people, with its unit, e.g. `21.5 °C`, `on`."""
    unit = entity.attributes.get("unit_of_measurement")
    return f"{entity.state} {unit}" if isinstance(unit, str) and unit and entity.known else entity.state


def entity_suggestion(entity: EntityState) -> Suggestion:
    """An entity in the list of a field: its id, its name, and its state now."""
    name = entity.name if entity.name != entity.entity_id else ""
    return Suggestion(entity.entity_id, name, origin=state_text(entity), present=entity.known)


def entity_suggestions(entities: tuple[EntityState, ...]) -> tuple[Suggestion, ...]:
    return tuple(entity_suggestion(entity) for entity in entities)


def value_text(value: object) -> str:
    """A value of an attribute, short, e.g. `255`, `["on", "off"]`."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 40 else text[:39] + "…"


def attribute_suggestions(entity: EntityState | None) -> tuple[Suggestion, ...]:
    """The attributes of an entity, with their values now; none for an unknown entity."""
    if entity is None:
        return ()
    return tuple(
        Suggestion(name, "", origin=value_text(value))
        for name, value in entity.attributes.items()
        if name not in ("friendly_name",)
    )


# -- what an unset option does ------------------------------------------------------------------------------------


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def value_placeholder(name: str, table: Mapping[str, Any], entity: EntityState | None) -> str | None:
    """
    What an unset option of an entity a fader or an encoder sets does, by its domain (`DOMAIN_VALUES`) and what the
    entity tells (the `min` and `max` of a `number`), e.g. `brightness, of a light`; None for an option the domain
    does not change.
    """
    entity_id = table.get("entity")
    if not isinstance(entity_id, str) or not ENTITY_ID.fullmatch(entity_id):
        return {
            "attribute": "by its domain",
            "min": "by its domain",
            "max": "by its domain",
            "service": "by its domain",
        }.get(name)
    domain = domain_of(entity_id)
    value = DOMAIN_VALUES.get(domain)
    attribute = table.get("attribute")
    own = value is not None and attribute in (None, value.attribute)
    of = f"of a {domain}"
    match name:
        case "attribute":
            if value is None or value.attribute is None:
                return "none: the state"
            return f"{value.attribute}, {of}"
        case "min" | "max":
            told = _number(entity.attributes.get(name)) if entity is not None else None
            if told is not None:
                return f"{told:g}, the entity's {name}"
            if not own or value is None:
                return "0" if name == "min" else "100"
            return f"{getattr(value, name):g}, {of}"
        case "service":
            if not own or value is None:
                return f"none: set one, nothing sets this of a {domain} by itself"
            return f"{value.service}, {of}"
        case "data":
            if not own or value is None:
                return 'none, e.g. { value = "{value}" }'
            return f'{{ {value.key} = "{{value}}" }}, {of}'
        case _:
            return None


# -- the connection -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Explanation:
    short: str
    """A few words for a pill, e.g. "bad token"."""
    hint: str
    """What to check."""


def explain(error: str) -> Explanation:
    """What an error of the connection to Home Assistant means."""
    lowered = error.lower()
    if "refused the token" in lowered:
        return Explanation("bad token", f"Home Assistant does not take the token. {TOKEN_HINT}")
    if "token" in lowered and ("needs" in lowered or "token_file" in lowered or "token_env" in lowered):
        return Explanation("no token", TOKEN_HINT)
    if "no websocket api" in lowered or "did not log in" in lowered:
        return Explanation("no Home Assistant", "Something else answers at `url`: check the address and the port.")
    if "did not answer" in lowered:
        return Explanation("no answer", "Home Assistant takes too long to answer: is it starting?")
    if "can't connect" in lowered or "refused" in lowered or "unreachable" in lowered:
        return Explanation("unreachable", "Nothing answers at `url`: check the address and that Home Assistant runs.")
    return Explanation("error", "")


def _entities(count: int) -> str:
    return f"{count} entit{'y' if count == 1 else 'ies'}"


def live_status(snapshot: Snapshot | None) -> Status:
    """How the daemon's connection to the API of Home Assistant is doing, for its page and the connections."""
    if snapshot is None:
        return Status(
            "unknown",
            Tone.NEUTRAL,
            "The daemon does not run, or gives no live view: once it runs, this tells how its connection is doing.",
        )
    if snapshot.homeassistant is None:
        return Status(
            "not in use",
            Tone.NEUTRAL,
            "The daemon connects only while a part shows or sets an entity, and `[homeassistant]` is in the file.",
        )
    return status_of(snapshot.homeassistant)


def status_of(state: HomeAssistantState) -> Status:
    version = f"Home Assistant {state.version}" if state.version else "Home Assistant"
    if state.connected and state.synced:
        watched = f", {state.watched} of them on the device" if state.watched else ""
        return Status(
            "connected", Tone.GOOD, f"Connected to {version} at {state.url}: {_entities(state.entities)}{watched}."
        )
    if state.connected:
        return Status("syncing", Tone.NEUTRAL, f"Connected to {version} at {state.url}, reading the entities.")
    if state.error is None:
        return Status("connecting", Tone.WARN, f"Connecting to Home Assistant at {state.url}.")
    explanation = explain(state.error)
    # a refused token stays refused: it takes another one and a reload
    retry = "" if explanation.short == "bad token" else RETRY
    text = " ".join(part for part in (f"Can't connect to {state.url}: {state.error}.", explanation.hint, retry) if part)
    return Status(explanation.short, Tone.BAD, text)


@dataclass(frozen=True)
class Tried:
    """The result of a test of the settings: what it says, and the entities it found (None when it failed)."""

    status: Status
    entities: tuple[EntityState, ...] | None = None
    error: str | None = None
    """Why it failed, in the words of the error."""


async def try_home_assistant(config: HomeAssistantConfig, fetch: Fetch) -> Tried:
    """Connects with `config` once, reads the entities and disconnects again: whether the daemon could use it."""
    try:
        fetched = await fetch(config)
    except ConfigError as e:
        return Tried(Status(f"Can't connect: {e}.", Tone.BAD, TOKEN_HINT), error=str(e))
    except HomeAssistantError as e:
        hint = explain(str(e)).hint
        return Tried(Status(f"Can't connect to {config.url}: {e}.", Tone.BAD, hint), error=str(e))
    except Exception as e:
        # anything else that went wrong: the read ends with a result, or the window would wait for it for good
        problem = f"{type(e).__name__}: {e}"
        return Tried(Status(f"Can't connect to {config.url}: {problem}.", Tone.BAD), error=problem)
    version = f"Home Assistant {fetched.version}" if fetched.version else "Home Assistant"
    return Tried(
        Status(f"Connected to {version} at {config.url}: {_entities(len(fetched.entities))}.", Tone.GOOD),
        fetched.entities,
    )


# -- the entities the GUI knows -----------------------------------------------------------------------------------

STALE_AFTER = 60.0
"""Seconds after which the entities are read again, the next time a field wants them."""


class EntityCache:
    """
    The entities of Home Assistant as the GUI read them last (see `try_home_assistant`), for the settings they were
    read with: other settings, or a minute later, read them again. One read at a time.
    """

    def __init__(self) -> None:
        self.config: HomeAssistantConfig | None = None
        """The settings the entities (or the error) are of."""
        self.entities: tuple[EntityState, ...] = ()
        self.error: str | None = None
        """Why the last read failed, None after one that worked (or before any)."""
        self.reading: HomeAssistantConfig | None = None
        """The settings being read with now, None while none is."""
        self.read_at: float | None = None
        self._by_id: dict[str, EntityState] = {}

    def wants(self, config: HomeAssistantConfig, now: float, again: bool = False) -> bool:
        """Whether to read the entities with `config` now: another one, stale ones, or `again` (none being read)."""
        if self.reading is not None:
            return False
        if config != self.config or self.read_at is None:
            return True
        return again or now - self.read_at >= STALE_AFTER

    def start(self, config: HomeAssistantConfig) -> None:
        self.reading = config

    def done(self, config: HomeAssistantConfig, tried: Tried, now: float) -> bool:
        """A read ended: its entities, or why not. Whether it is news (a read of settings no longer wanted is too)."""
        if self.reading == config:
            self.reading = None
        self.config = config
        self.read_at = now
        if tried.entities is not None:
            self.entities = tried.entities
            self.error = None
        else:
            self.entities = ()
            self.error = tried.error or tried.status.text
        self._by_id = {entity.entity_id: entity for entity in self.entities}
        return True

    def entity(self, entity_id: object) -> EntityState | None:
        return self._by_id.get(entity_id) if isinstance(entity_id, str) else None


def why_no_entities(
    config: HomeAssistantConfig | str | None, cache: EntityCache, live: HomeAssistantState | None
) -> str:
    """
    Why a field of an entity has no suggestions, for one line under it; "" while it has them. `config` is that of
    `section_config`, `live` the daemon's connection.
    """
    if config is None:
        return "No suggestions: add `[homeassistant]` with the address of Home Assistant and a token."
    if isinstance(config, str):
        return f"No suggestions: the settings of Home Assistant have a problem ({config})."
    if cache.reading == config:
        return "Reading the entities of Home Assistant…"
    if cache.config != config:
        return ""
    if cache.error is not None:
        daemon = (
            f" The daemon is connected, with {_entities(live.entities)}: the window may lack the token it has."
            if live is not None and live.connected
            else ""
        )
        explanation = explain(cache.error)
        return f"No suggestions: {explanation.hint or cache.error}{daemon}"
    if not cache.entities:
        return "No suggestions: Home Assistant has no entities."
    return ""
