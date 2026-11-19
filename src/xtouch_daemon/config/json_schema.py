"""
The JSON Schema of the configuration file: editors with a TOML language server (Taplo, Tombi) complete the options
from it, show their help on hover and mark mistakes while typing; so do AI assistants that read it. The file says
where it is with a `#:schema` line (see `config.example.toml`).

It is made from the pydantic models, so it follows them. The sections of the slots (`[channel.*]`, `[pool.*]`,
`[state.*]`, `[slots]`, `[controls]`) are checked by `slots.model.Scene` and `config.slots.setup()` rather than by one
model, so their schemas are put together here: a channel takes the options of its strip, a pool and a candidate the
look of theirs. It is looser than the daemon: whatever the daemon takes, the schema takes; `check-config` finds the
rest (an option of another type of strip, an id that is reserved, a channel that is missing).
"""

import json
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode, models_json_schema

from xtouch_daemon.config.model import Config
from xtouch_daemon.config.slots import CHANNEL_ONLY
from xtouch_daemon.config.strips import STRIP_MODELS
from xtouch_daemon.hardware import protocol
from xtouch_daemon.slots.model import (
    APP_OPTIONS,
    DEVICE_OPTIONS,
    LOOK_OPTIONS,
    MEMBER_OPTIONS,
    AppsConfig,
    AppsPoolConfig,
    AutoConfig,
    ChannelConfig,
    ControlsConfig,
    DevicesConfig,
    PeopleConfig,
    PeoplePoolConfig,
    PoolConfig,
    StateConfig,
)

SCHEMA_URL = "https://markusressel.github.io/xtouch-daemon/latest/config.schema.json"
"""Where the documentation publishes the schema of the latest release (`docs/config.schema.json`)."""

_ID = {"pattern": "^[a-z0-9_]+$"}
_SLOT = {"pattern": f"^0*[1-{protocol.STRIPS}]$"}
_POOLS: dict[str, type[BaseModel]] = {
    "auto": AutoConfig,
    "apps": AppsConfig,
    "people": PeopleConfig,
    "devices": DevicesConfig,
}
_OWN_POOLS: tuple[type[BaseModel], ...] = (PoolConfig, AppsPoolConfig, PeoplePoolConfig)
_SECTIONS: tuple[type[BaseModel], ...] = (
    Config,
    ChannelConfig,
    *_POOLS.values(),
    *_OWN_POOLS,
    StateConfig,
    ControlsConfig,
    *STRIP_MODELS,
)


def config_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) of the configuration file."""
    mode: JsonSchemaMode = "validation"
    refs, top = models_json_schema([(model, mode) for model in _SECTIONS], ref_template="#/$defs/{model}")
    defs: dict[str, Any] = top["$defs"]

    def of(model: type[BaseModel]) -> dict[str, Any]:
        return defs[refs[(model, mode)]["$ref"].removeprefix("#/$defs/")]

    # each option of a strip once, in the $defs: channels, pools and candidates refer to them
    strip_options = _strip_options([of(model) for model in STRIP_MODELS])
    strip = {name: {"$ref": f"#/$defs/strip.{name}"} for name in strip_options}
    _widen_chord(defs["SwitchingConfig"])
    channel = _open(of(ChannelConfig), strip, keep_own=CHANNEL_ONLY | {"type"})
    pool_look = {name: value for name, value in strip.items() if name not in MEMBER_OPTIONS}
    candidate = {
        "type": "object",
        "description": "A candidate as a table: what it shows, maybe a condition, and options of the place.",
        "properties": {
            "show": {"type": "string", "description": "The channel or pool it shows, or - for nothing."},
            "when": {"type": "string", "description": "The condition, e.g. `call and not gaming`."},
            **{name: value for name, value in strip.items() if name in LOOK_OPTIONS | APP_OPTIONS | DEVICE_OPTIONS},
        },
        "required": ["show"],
        "additionalProperties": False,
    }
    candidates = {
        "anyOf": [
            {"type": "string", "description": "A channel or pool, maybe with a condition: `voip if call`."},
            {"type": "array", "items": {"anyOf": [{"type": "string"}, candidate]}},
        ]
    }
    controls = {"$ref": refs[(ControlsConfig, mode)]["$ref"]}
    config = of(Config)
    properties: dict[str, Any] = {
        **config["properties"],
        "channel": {
            "type": "object",
            "description": "The channels: what the strips control (devices, applications, people, Home Assistant).",
            "propertyNames": _ID,
            "additionalProperties": channel,
        },
        "pool": {
            "type": "object",
            "description": "The built-in pools (auto, apps, people, devices) and pools of your own.",
            "propertyNames": _ID,
            "properties": {name: _open(of(model), pool_look) for name, model in _POOLS.items()},
            "additionalProperties": {"anyOf": [_open(of(model), pool_look) for model in _OWN_POOLS]},
        },
        "state": {
            "type": "object",
            "description": "The states and modes that the conditions of the slots ask about.",
            "propertyNames": _ID,
            "additionalProperties": {"$ref": refs[(StateConfig, mode)]["$ref"]},
        },
        "slots": {
            "type": "object",
            "description": "The candidates of each slot (1 to 8, from the left): it shows the first whose "
            "condition holds.",
            "propertyNames": _SLOT,
            "additionalProperties": candidates,
        },
        "controls": {
            "type": "object",
            "description": "Controls of a slot that act whatever it shows (1 to 8): one table, or a list of them.",
            "propertyNames": _SLOT,
            "additionalProperties": {"anyOf": [controls, {"type": "array", "items": controls}]},
        },
    }
    for model in (Config, *STRIP_MODELS):
        # inlined above, or parts of the options of channels, pools and candidates
        defs.pop(refs[(model, mode)]["$ref"].removeprefix("#/$defs/"))
    for model in (ChannelConfig, *_POOLS.values(), *_OWN_POOLS):
        defs.pop(refs[(model, mode)]["$ref"].removeprefix("#/$defs/"))
    defs |= {f"strip.{name}": value for name, value in strip_options.items()}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        "title": "xtouch-daemon configuration",
        "description": "The configuration of xtouch-daemon (config.toml); `xtouch-daemon check-config` checks "
        "the rest.",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "$defs": dict(sorted(defs.items())),
    }


def schema_text() -> str:
    """The schema as the file `config.schema.json` has it."""
    return json.dumps(config_schema(), indent=2, ensure_ascii=False) + "\n"


def _strip_options(models: list[dict[str, Any]]) -> dict[str, Any]:
    """
    The options of every type of strip but `type`, by name: an option that differs between the types takes what
    any of them takes, without a default (that depends on the type).
    """
    found: dict[str, list[dict[str, Any]]] = {}
    for model in models:
        for name, value in model["properties"].items():
            if name != "type":
                found.setdefault(name, []).append(value)
    options: dict[str, Any] = {}
    for name, values in found.items():
        kinds = list({_bare(value): _bare_schema(value) for value in values}.values())
        description = next((value["description"] for value in values if "description" in value), None)
        merged = dict(values[0]) if len(kinds) == 1 else {"anyOf": kinds}
        if len({json.dumps(value.get("default"), sort_keys=True) for value in values}) > 1:
            merged.pop("default", None)
        merged.pop("title", None)
        if description is not None:
            merged["description"] = description
        options[name] = merged
    return options


def _bare_schema(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in ("title", "default", "description")}


def _bare(value: dict[str, Any]) -> str:
    return json.dumps(_bare_schema(value), sort_keys=True)


def _open(model: dict[str, Any], strip: dict[str, Any], keep_own: frozenset[str] | None = None) -> dict[str, Any]:
    """
    A model that takes the options of a strip besides its own (`_Open`), as a closed table. The options of the strip
    win (they say more), but for `keep_own`; all of the model's own win without it.
    """
    own: dict[str, Any] = model["properties"]
    if keep_own is None:
        properties = strip | own
    else:
        properties = {name: value for name, value in own.items() if name not in strip or name in keep_own}
        properties |= {name: value for name, value in strip.items() if name not in keep_own}
    result: dict[str, Any] = {"type": "object"}
    if "description" in model:
        result["description"] = model["description"]
    result["properties"] = properties
    if "required" in model:
        result["required"] = model["required"]
    result["additionalProperties"] = False
    return result


def _widen_chord(switching: dict[str, Any]) -> None:
    """`switching.chord` takes a table too: `chord = { strips = [1, 8], action = "toggle:call" }`."""
    chord = switching["properties"]["chord"]
    strips = {key: value for key, value in chord.items() if key not in ("title", "default", "description")}
    table = {
        "type": "object",
        "properties": {"strips": strips, "action": switching["properties"]["chord_action"]},
        "additionalProperties": False,
    }
    switching["properties"]["chord"] = {
        **{key: value for key, value in chord.items() if key in ("title", "default", "description")},
        "anyOf": [strips, table],
    }
