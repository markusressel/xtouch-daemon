"""
The messages of the voice chat bridge (see `bridge.py`) as pydantic models: one JSON object per line, each way. The
docstrings of the fields are the specification: `docs/voice-chat-bridge.schema.json` is made from them
(`xtouch-daemon schema --bridge`), and `docs/reference/voice-chat-bridge.md` explains it.

Both sides ignore keys they don't know. The daemon takes the state of a plugin leniently, as it always did: it clamps
a volume or a level that is out of range instead of refusing the line, and takes a number written as text. The schema
says what a plugin should send.
"""

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictStr, WithJsonSchema
from pydantic.json_schema import JsonSchemaMode, models_json_schema

from xtouch_daemon.voip.provider import VOLUME_LIMIT, Capability, Participant

PROTOCOL = 1
"""The version of the protocol that this daemon speaks."""
SCHEMA_URL = "https://markusressel.github.io/xtouch-daemon/latest/voice-chat-bridge.schema.json"
"""Where the documentation publishes the schema of the latest release (`docs/voice-chat-bridge.schema.json`)."""


class Message(BaseModel):
    # keys of newer versions are ignored; the docstrings of the fields are their descriptions in the schema
    model_config = ConfigDict(extra="ignore", frozen=True, use_attribute_docstrings=True)


def _id(value: object) -> object:
    # a number of the client is taken as text: the daemon compares ids, it doesn't count with them
    return str(value) if isinstance(value, str | int) else value


def _number(value: object) -> float:
    try:
        return float(value)  # pyright: ignore[reportArgumentType]: any JSON value
    except (TypeError, ValueError, OverflowError) as e:
        # pydantic turns only a ValueError into a validation error
        raise ValueError(str(e)) from e


def _volume(value: object) -> int:
    try:
        return max(0, min(VOLUME_LIMIT, round(_number(value))))
    except OverflowError as e:  # round() of infinity
        raise ValueError(str(e)) from e


def _level(value: object) -> float | None:
    return None if value is None else max(0.0, min(1.0, _number(value)))


def _text_or_none(value: object) -> str | None:
    return str(value) if value else None


def _channel(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


Level = Annotated[
    float | None,
    BeforeValidator(_level),
    WithJsonSchema({"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]}),
]
"""A level, 0..1, or None if the client can't tell; one out of range is clamped."""
Truth = Annotated[bool, BeforeValidator(bool), WithJsonSchema({"type": "boolean"})]
"""A switch: any JSON value is taken for its truth, as Python sees it."""


class Greeting(Message):
    """The first line of the daemon to a plugin that connects."""

    daemon: Literal["xtouch-daemon"]
    """Who answers: always `xtouch-daemon`."""
    version: str
    """The version of the daemon, e.g. `0.2.0`."""
    protocol: int
    """
    The version of the protocol that the daemon speaks. A plugin that speaks an older one can tell from it whether
    the daemon understands it.
    """


class Refusal(Message):
    """The only line of the daemon to a plugin that it refuses; the daemon closes the connection after it."""

    error: str
    """
    Why the daemon refuses the plugin, e.g. `another mumble plugin is connected` while a plugin of the same client is
    connected.
    """


class ParticipantState(Message):
    """A participant of the voice chat, as the plugin knows them."""

    id: Annotated[str, BeforeValidator(_id), WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "integer"}]})]
    """
    What the client knows the participant by. It stays the same while they are there. A number is taken as text: the
    commands of the daemon send it back as a string.
    """
    name: StrictStr
    """The name of the participant: the LCD shows it, and the daemon keeps volume and mute by it."""
    talking: Truth = False
    """The participant talks right now: the LCD lights in `talking_color`."""
    muted: Truth = False
    """The user muted the participant, for themselves only (in Mumble: the local mute). Mute lights."""
    volume: Annotated[
        int,
        BeforeValidator(_volume),
        WithJsonSchema({"type": "number", "minimum": 0, "maximum": VOLUME_LIMIT}),
    ] = 100
    """
    The volume of the participant for the user, in percent, 0 to 200; the fader shows it. The daemon rounds it and
    clamps it to 0..200.
    """
    level: Level = None
    """
    How loud the participant talks, 0 to 1, after their volume: the peak since the line before. The meter shows it
    with `meter_point = "post_fader"`. Leave it out if the client can't tell. The daemon clamps it to 0..1.
    """
    pre_fader_level: Level = None
    """
    How loud the participant talks, 0 to 1, before their volume: the peak since the line before. The meter shows it
    with `meter_point = "pre_fader"`, so it stays up while the fader is down. Without it, the meter shows `level`.
    The daemon clamps it to 0..1.
    """

    def participant(self) -> Participant:
        """The participant for the providers."""
        return Participant(
            id=self.id,
            name=self.name,
            talking=self.talking,
            muted=self.muted,
            volume=self.volume,
            level=self.level,
            pre_fader_level=self.pre_fader_level,
        )


class PluginState(Message):
    """
    A line of the plugin: its whole state, on every change, and while someone talks for the levels (e.g. 20 times a
    second).
    """

    protocol: int = PROTOCOL
    """
    The version of the protocol that the plugin speaks. The daemon ignores (and logs) the lines of a version it does
    not speak.
    """
    client: Annotated[str | None, BeforeValidator(_text_or_none)] = None
    """The voice chat client, e.g. `mumble`: the log and the GUI name it."""
    channel: Annotated[str | None, BeforeValidator(_channel)] = None
    """The channel the user is in: the GUI shows it. Leave it out, or empty, outside a channel."""
    capabilities: tuple[Capability, ...] = ()
    """
    What the plugin can do besides telling who is there and who talks: `volume` (the fader sets volumes), `mute`
    (Mute mutes) and `levels` (it sends `level`, the meter shows it).
    """
    participants: tuple[ParticipantState, ...]
    """The participants in the channel of the user, without the user, in the order they came."""


class VolumeChange(Message):
    """The volume a fader sets for a participant."""

    id: str
    """The `id` of the participant, as text."""
    volume: int
    """The volume, in percent, 0 to 200. The plugin clamps a volume out of its range."""


class SetVolume(Message):
    """A command of the daemon: set the volume of a participant. Needs the capability `volume`."""

    set_volume: VolumeChange
    """The participant and their new volume."""


class MuteChange(Message):
    """The mute that Mute sets for a participant."""

    id: str
    """The `id` of the participant, as text."""
    muted: bool
    """True mutes the participant for the user, false unmutes them."""


class SetMuted(Message):
    """A command of the daemon: mute or unmute a participant for the user. Needs the capability `mute`."""

    set_muted: MuteChange
    """The participant and their new mute."""


FROM_DAEMON: tuple[type[Message], ...] = (Greeting, Refusal, SetVolume, SetMuted)
"""What the daemon sends to a plugin."""
FROM_PLUGIN: tuple[type[Message], ...] = (PluginState,)
"""What a plugin sends to the daemon."""


def encode(message: Message) -> bytes:
    """A line of the daemon: compact, as the Mumble plugin parses it (`"key":value`, without spaces)."""
    return json.dumps(message.model_dump(mode="json"), separators=(",", ":")).encode() + b"\n"


def bridge_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) of a line of the bridge, either way."""
    mode: JsonSchemaMode = "validation"
    refs, top = models_json_schema(
        [(model, mode) for model in (*FROM_PLUGIN, *FROM_DAEMON)], ref_template="#/$defs/{model}"
    )
    defs: dict[str, Any] = top["$defs"]

    def any_of(models: tuple[type[Message], ...]) -> dict[str, Any]:
        return {"anyOf": [refs[(model, mode)] for model in models]}

    defs["FromPlugin"] = {"description": "A line of the plugin to the daemon.", **any_of(FROM_PLUGIN)}
    defs["FromDaemon"] = {"description": "A line of the daemon to the plugin.", **any_of(FROM_DAEMON)}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        "title": "xtouch-daemon voice chat bridge",
        "description": "A line of the voice chat bridge between xtouch-daemon and a plugin of a voice chat client, "
        "one JSON object per line on the socket `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`. Both sides ignore keys "
        "they don't know.",
        "anyOf": [{"$ref": "#/$defs/FromPlugin"}, {"$ref": "#/$defs/FromDaemon"}],
        "$defs": dict(sorted(defs.items())),
    }


def schema_text() -> str:
    """The schema as the file `voice-chat-bridge.schema.json` has it."""
    return json.dumps(bridge_schema(), indent=2, ensure_ascii=False) + "\n"
