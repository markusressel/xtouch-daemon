"""
The messages of the live view as lines of JSON. A line of another version, or one that can't be read, is skipped.
"""

import json
from dataclasses import asdict
from typing import Any

from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import (
    VERSION,
    EndPreview,
    KeepPreview,
    MqttState,
    Play,
    Reply,
    Request,
    SetMode,
    SetOverride,
    SlotsState,
    SlotView,
    Snapshot,
    StartPreview,
    StateView,
    StripState,
    VoipState,
)
from xtouch_daemon.slots.outcomes import Situation


def encode(snapshot: Snapshot) -> bytes:
    return json.dumps({"version": VERSION, **asdict(snapshot)}, separators=(",", ":")).encode() + b"\n"


def decode(line: bytes) -> Snapshot | None:
    """
    A snapshot of the daemon, None for a line of another version or a reply. Raises ValueError (or KeyError) for a
    line that is neither.
    """
    message = decode_message(line)
    return message if isinstance(message, Snapshot) else None


def decode_message(line: bytes) -> Snapshot | Reply | None:
    """A line of the daemon: a snapshot or a reply, None for a snapshot of another version."""
    data = json.loads(line)
    if "reply" in data:
        return Reply(data["reply"], bool(data["ok"]), str(data.get("message", "")))
    if data.get("version") != VERSION:
        return None
    strips = tuple(
        StripState(
            color=strip["color"],
            text=(strip["text"][0], strip["text"][1]),
            leds=dict(strip["leds"]),
            ring=strip["ring"],
            ring_mode=strip["ring_mode"],
            fader=strip["fader"],
            touched=strip["touched"],
            meter=strip["meter"],
        )
        for strip in data["strips"]
    )
    mqtt_state = data.get("mqtt_state")
    return Snapshot(
        data["config"],
        data["device"],
        data["sound_server"],
        data["mqtt"],
        strips,
        MqttState(**mqtt_state) if mqtt_state is not None else None,
        data.get("daemon_version"),
        bool(data.get("preview", False)),
        tuple(data.get("features", ())),
        _voip(data.get("voip")),
        _slots(data.get("slots")),
        bool(data.get("virtual", False)),
        bool(data.get("simulated", False)),
    )


def _slots(value: dict[str, Any] | None) -> SlotsState | None:
    if value is None:
        return None
    return SlotsState(
        value["mode"],
        value["mode_pick"],
        tuple(SlotView(**{**slot, "why": tuple(slot["why"])}) for slot in value["slots"]),
        tuple(StateView(**state) for state in value["states"]),
        {pool: tuple(members) for pool, members in value["waiting"].items()},
    )


def _voip(value: dict[str, Any] | None) -> VoipState | None:
    if value is None:
        return None
    return VoipState(
        value["provider"],
        value["connected"],
        value["client"],
        value["channel"],
        value["participants"],
        tuple(value.get("names", ())),
        tuple(value.get("ids", ())),
    )


def encode_reply(reply: Reply) -> bytes:
    return json.dumps({"reply": reply.kind, "ok": reply.ok, "message": reply.message}).encode() + b"\n"


_REQUEST_NAMES: dict[type, str] = {
    StartPreview: "preview",
    KeepPreview: "keep_preview",
    EndPreview: "end_preview",
    SetMode: "mode",
    SetOverride: "override",
    Play: "play",
}

_EVENTS: dict[str, type] = {
    "fader_moved": protocol.FaderMoved,
    "fader_touched": protocol.FaderTouched,
    "button_pressed": protocol.ButtonPressed,
    "encoder_turned": protocol.EncoderTurned,
    "encoder_pressed": protocol.EncoderPressed,
}
"""The events a `Play` carries, by their names on the wire."""
_EVENT_NAMES = {kind: name for name, kind in _EVENTS.items()}


def encode_request(request: Request) -> bytes:
    data: dict[str, Any] = {"request": _REQUEST_NAMES[type(request)]}
    if isinstance(request, StartPreview):
        data["config"] = request.config
        if request.situation is not None:
            situation = request.situation
            data["situation"] = {
                "mode": situation.mode,
                "on": sorted(situation.on),
                "flipped": sorted(situation.flipped),
                "people": situation.people,
                "apps": situation.apps,
                "devices": situation.devices,
            }
    elif isinstance(request, SetMode):
        data["mode"] = request.mode
    elif isinstance(request, SetOverride):
        data |= {"state": request.state, "value": request.value}
    elif isinstance(request, Play):
        data |= {"event": _EVENT_NAMES[type(request.event)]} | asdict(request.event)
    return json.dumps(data).encode() + b"\n"


def decode_request(line: bytes) -> Request:
    """A request of a client. Raises ValueError for a line that is none."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON ({e})") from e
    match data:
        case {"request": "preview", "config": str() | None as config}:
            situation = data.get("situation")
            return StartPreview(config, None if situation is None else _situation(situation))
        case {"request": "keep_preview"}:
            return KeepPreview()
        case {"request": "end_preview"}:
            return EndPreview()
        case {"request": "mode", "mode": str(mode)}:
            return SetMode(mode)
        case {"request": "override", "state": str(state), "value": str(value)}:
            return SetOverride(state, value)
        case {"request": "play", "event": str(name), "strip": int(strip)} if name in _EVENTS:
            if not 0 <= strip < protocol.STRIPS:
                raise ValueError(f"no strip {strip}")
            return Play(_play_event(name, strip, data))
        case _:
            raise ValueError("unknown")


def _situation(value: Any) -> Situation:
    """The situation of a `StartPreview`. Raises ValueError for one that doesn't fit."""
    match value:
        case {
            "mode": str(mode),
            "on": [*on],
            "flipped": [*flipped],
            "people": int(people),
            "apps": int(apps),
            "devices": int(devices),
        } if all(isinstance(name, str) for name in [*on, *flipped]) and min(people, apps, devices) >= 0:
            return Situation(mode, frozenset(on), frozenset(flipped), people, apps, devices)
        case _:
            raise ValueError("not a situation")


def _play_event(name: str, strip: int, data: dict[str, Any]) -> protocol.StripEvent:
    """The event of a `Play` request. Raises ValueError for one that doesn't fit."""
    match name, data:
        case "fader_moved", {"value": int(value)} if 0 <= value <= protocol.FADER_MAX:
            return protocol.FaderMoved(strip, value)
        case "fader_touched", {"touched": bool(touched)}:
            return protocol.FaderTouched(strip, touched)
        case "button_pressed", {"button": int(button), "pressed": bool(pressed)} if button in set(protocol.Button):
            return protocol.ButtonPressed(strip, protocol.Button(button), pressed)
        case "encoder_turned", {"steps": int(steps)}:
            return protocol.EncoderTurned(strip, steps)
        case "encoder_pressed", {"pressed": bool(pressed)}:
            return protocol.EncoderPressed(strip, pressed)
        case _:
            raise ValueError(f"not a {name} event")
