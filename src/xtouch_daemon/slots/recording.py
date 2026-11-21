"""
Observations of the real system over time, as lines of JSON: recorded from the sound server, the processes and the
voice chat of the running daemon, and read back to replay them through a `Simulation`.
"""

import json
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.presets import PRESETS
from xtouch_daemon.live.codec import decode_message
from xtouch_daemon.live.messages import Snapshot, VoipState
from xtouch_daemon.slots.inputs import Attendee, Observation, SoundDevice, app_matches

LIVE_TIMEOUT = 1.0
"""Seconds to wait for a snapshot of the running daemon."""


def stream_name(app: str, binary: str) -> str:
    """An application as `app_matches()` takes it: its name, and its binary if that is another one."""
    return app if not binary or binary.lower() == app.lower() else f"{app} ({binary})"


@dataclass
class Observer:
    """Turns readings into observations, keeping the order in which applications started to play."""

    started: dict[str, float] = field(default_factory=dict)
    apps: dict[str, str] = field(default_factory=dict)
    """The name of the application of the streams of each name (`stream_name()`), as the sound server says it."""

    def observe(
        self,
        audio: AudioState,
        processes: frozenset[str],
        voip: VoipState | None,
        now: float,
        homeassistant: frozenset[str] = frozenset(),
        absent: frozenset[str] = frozenset(),
    ) -> Observation:
        names = [stream_name(stream.app, stream.binary) for stream in audio.streams]
        for stream in audio.streams:
            self.apps[stream_name(stream.app, stream.binary)] = stream.app
        for name in names:
            self.started.setdefault(name, now)
        for name in list(self.started):
            if name not in names:
                del self.started[name]
        devices = {value for device in (*audio.outputs, *audio.inputs) for value in (device.name, device.description)}
        return Observation(
            playing=tuple(sorted(set(names), key=lambda name: (self.started[name], name))),
            recording=tuple(sorted({stream_name(c.app, c.binary) for c in audio.captures if c.recording})),
            voice_chat=voip is not None and voip.connected and bool(voip.channel),
            people=attendees(voip) if voip is not None else (),
            processes=processes,
            devices=frozenset(device for device in devices if device),
            sound_devices=tuple(
                SoundDevice(device.name, device.description, device.direction.value)
                for device in (*audio.outputs, *audio.inputs)
            ),
            defaults=frozenset(name for name in (audio.default_output, audio.default_input) if name),
            homeassistant=homeassistant,
            absent=absent,
        )


def attendees(voip: VoipState) -> tuple[Attendee, ...]:
    """The people in the voice chat; from an older daemon without their ids, by name."""
    ids = voip.ids or voip.names
    return tuple(Attendee(id, name) for id, name in zip(ids, voip.names, strict=True))


def watched_processes(extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """
    The parts of process names worth recording: those of every preset, and `extra`. Not all of them: short-lived
    processes would make a line every few seconds.
    """
    names = (name for preset in PRESETS.values() for name in preset.processes or ())
    return tuple(dict.fromkeys((*names, *extra)))


def only_watched(processes: frozenset[str], watched: tuple[str, ...]) -> frozenset[str]:
    """
    The processes worth recording, by the name of their program only: programs that rewrite their command line
    (Chromium's helpers) have it all as their name, with IDs that don't belong in a log.
    """
    names = {Path(process.split()[0]).name for process in processes if process.strip()}
    return frozenset(name for name in names if app_matches(name, watched))


def to_line(now: float, observation: Observation) -> str:
    return json.dumps(
        {
            "t": round(now, 3),
            "playing": list(observation.playing),
            "recording": list(observation.recording),
            "voice_chat": observation.voice_chat,
            "people": [[person.id, person.name] for person in observation.people],
            "processes": sorted(observation.processes),
            "devices": sorted(observation.devices),
            "sound_devices": [[d.name, d.description, d.direction] for d in observation.sound_devices],
            "defaults": sorted(observation.defaults),
            "homeassistant": sorted(observation.homeassistant),
            "absent": sorted(observation.absent),
        }
    )


def from_line(line: str) -> tuple[float, Observation]:
    data = json.loads(line)
    return float(data["t"]), Observation(
        playing=tuple(data["playing"]),
        recording=tuple(data["recording"]),
        voice_chat=bool(data["voice_chat"]),
        # a recording made before the ids: a name stands for its id
        people=tuple(
            Attendee(*person) if isinstance(person, list) else Attendee(person, person) for person in data["people"]
        ),
        processes=frozenset(data["processes"]),
        devices=frozenset(data["devices"]),
        # a recording made before the pool devices has none of them
        sound_devices=tuple(SoundDevice(*device) for device in data.get("sound_devices", ())),
        defaults=frozenset(data.get("defaults", ())),
        homeassistant=frozenset(data["homeassistant"]),
        # a recording made before custom channels has none absent
        absent=frozenset(data.get("absent", ())),
    )


def read_log(path: Path) -> list[tuple[float, Observation]]:
    return [from_line(line) for line in path.read_text().splitlines() if line.strip()]


def read_voip(path: Path) -> VoipState | None:
    """The voice chat of the running daemon, from the first snapshot of its live view; None without one."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(LIVE_TIMEOUT)
            sock.connect(str(path))
            with sock.makefile("rb") as lines:
                for line in lines:
                    message = decode_message(line)
                    if isinstance(message, Snapshot):
                        return message.voip
    except OSError:
        return None
    return None


def record(
    log: Path,
    read_audio: Callable[[], AudioState],
    read_processes: Callable[[], frozenset[str]],
    read_voice: Callable[[], VoipState | None],
    clock: Callable[[], float],
    wait: Callable[[float], None],
    interval: float,
    samples: int | None = None,
) -> None:
    """
    Appends an observation to `log` every `interval` seconds while it differs from the one before (so a quiet day
    stays small), `samples` times or until interrupted.
    """
    observer = Observer()
    last: Observation | None = None
    count = 0
    with log.open("a") as file:
        while samples is None or count < samples:
            now = clock()
            observation = observer.observe(read_audio(), read_processes(), read_voice(), now)
            if observation != last:
                file.write(to_line(now, observation) + "\n")
                file.flush()
                last = observation
            count += 1
            wait(interval)
