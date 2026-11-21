"""
The messages of the voice chat bridge (`voip.protocol`): their JSON Schema is current where the documentation
publishes it, and the examples of the reference page are messages the models and the schema take, key by key.
"""

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tests.support.cli import invoke
from xtouch_daemon import __version__
from xtouch_daemon.voip.protocol import (
    FROM_DAEMON,
    PROTOCOL,
    Greeting,
    Message,
    MuteChange,
    ParticipantState,
    PluginState,
    Refusal,
    SetMuted,
    SetVolume,
    VolumeChange,
    bridge_schema,
    encode,
    schema_text,
)

ROOT = Path(__file__).parent.parent.parent
DOCS = ROOT / "docs"
PAGE = DOCS / "reference" / "voice-chat-bridge.md"
SCHEMA = bridge_schema()
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)

_BY_KEY: dict[str, type[Message]] = {
    "daemon": Greeting,
    "error": Refusal,
    "set_volume": SetVolume,
    "set_muted": SetMuted,
    "participants": PluginState,
}


def problems(message: dict[str, Any], kind: str | None = None) -> list[str]:
    """What the schema finds wrong in a message, of any kind or of the kind of `$defs`."""
    validator = VALIDATOR if kind is None else VALIDATOR.evolve(schema={**SCHEMA, "$ref": f"#/$defs/{kind}"})
    return [error.message for error in validator.iter_errors(message)]


def unknown_keys(model: type[Message], data: dict[str, Any]) -> list[str]:
    """The keys of `data` that `model` doesn't have, also in its messages inside: those it would ignore."""
    found = [key for key in data if key not in model.model_fields]
    inner: dict[str, type[Message]] = {
        "participants": ParticipantState,
        "set_volume": VolumeChange,
        "set_muted": MuteChange,
    }
    for key, value in data.items():
        if key in inner and key in model.model_fields:
            for each in value if isinstance(value, list) else [value]:
                found += [f"{key}.{name}" for name in unknown_keys(inner[key], each)]
    return found


def documented_messages() -> list[tuple[str, dict[str, Any]]]:
    """The JSON objects of the reference page, by number."""
    decoder = json.JSONDecoder()
    found: list[tuple[str, dict[str, Any]]] = []
    for block in re.findall(r"```json\n(.*?)```", PAGE.read_text(encoding="utf-8"), re.S):
        text = block.strip()
        while text:
            message, end = decoder.raw_decode(text)
            found.append((f"#{len(found)}", message))
            text = text[end:].strip()
    return found


def test_the_published_schema_is_current():
    # `just schema` writes it
    assert (DOCS / "voice-chat-bridge.schema.json").read_text(encoding="utf-8") == schema_text()


def test_it_is_a_valid_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_the_command_prints_it():
    result = invoke("schema", "--bridge")
    assert result.exit_code == 0
    assert result.output == schema_text()


def test_the_page_links_the_schema():
    assert "(../voice-chat-bridge.schema.json)" in PAGE.read_text(encoding="utf-8")


def test_the_page_has_an_example_of_each_message():
    assert sorted({next(key for key in message if key in _BY_KEY) for _, message in documented_messages()}) == sorted(
        _BY_KEY
    )


@pytest.mark.parametrize(("number", "message"), documented_messages(), ids=lambda value: value if "#" in value else "")
def test_the_examples_of_the_page_are_messages(number: str, message: dict[str, Any]):
    model = next(_BY_KEY[key] for key in message if key in _BY_KEY)
    model.model_validate(message)
    assert unknown_keys(model, message) == []
    assert problems(message, model.__name__) == []
    assert problems(message) == []


def test_the_lines_of_the_daemon_are_compact_and_follow_the_schema():
    lines = [
        Greeting(daemon="xtouch-daemon", version=__version__, protocol=PROTOCOL),
        Refusal(error="another plugin is connected"),
        SetVolume(set_volume=VolumeChange(id="12", volume=80)),
        SetMuted(set_muted=MuteChange(id="12", muted=True)),
    ]
    assert [encode(line) for line in lines[2:]] == [
        b'{"set_volume":{"id":"12","volume":80}}\n',
        b'{"set_muted":{"id":"12","muted":true}}\n',
    ]
    for line in lines:
        assert type(line) in FROM_DAEMON
        assert problems(json.loads(encode(line)), "FromDaemon") == []


@pytest.mark.parametrize(
    ("message", "mistake"),
    [
        ({"participants": [{"id": "1"}]}, "'name' is a required property"),
        ({"participants": [{"id": "1", "name": "Ann", "volume": 250}]}, "250 is greater than the maximum of 200"),
        ({"participants": [{"id": "1", "name": "Ann", "level": 1.5}]}, "1.5 is not valid"),
        ({"participants": [], "capabilities": ["fly"]}, "'fly' is not one of"),
        ({"set_volume": {"id": 12, "volume": 80}}, "12 is not of type 'string'"),
    ],
)
def test_the_schema_marks_what_a_plugin_should_not_send(message: dict[str, Any], mistake: str):
    # the daemon clamps an out-of-range volume or level, but a plugin should not send one
    kind = "SetVolume" if "set_volume" in message else "PluginState"
    found = problems(message, kind)
    assert any(mistake in each for each in found), found


def test_every_key_has_its_help():
    for name, definition in SCHEMA["$defs"].items():
        assert "description" in definition, name
        for key, value in definition.get("properties", {}).items():
            assert "description" in value, f"{name}.{key}"
