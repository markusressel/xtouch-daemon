"""
What the running daemon is connected to (the device, the sound server, Home Assistant, the voice chat), for the
status of the service at the top of the window: its pill tells the first problem, a click lists them all.
"""

from dataclasses import dataclass

from xtouch_daemon.gui.domain.broker import live_status
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.live.messages import Snapshot

_ORDER = (Tone.BAD, Tone.WARN, Tone.NEUTRAL, Tone.GOOD)
"""The tones from the worst one."""


@dataclass(frozen=True)
class Connection:
    name: str
    """What it is, e.g. "Home Assistant" or the name of the device."""
    short: str
    """A word or two for it in the pill of the service, e.g. "device"."""
    status: Status
    settings: str | None = None
    """The page of its settings (e.g. "mqtt"), None for none."""


def connections(snapshot: Snapshot | None, device_name: str) -> tuple[Connection, ...]:
    """The connections of the daemon, none without a live view: Home Assistant and the voice chat where configured."""
    if snapshot is None:
        return ()
    device = (
        Status("connected", Tone.GOOD, "The daemon drives the device.")
        if snapshot.device
        else Status(
            "not connected",
            Tone.WARN,
            "The device is not there: the daemon shows on it what it should once it is (plugged in, switched on).",
        )
    )
    sound = (
        Status("connected", Tone.GOOD, "The daemon reads and sets the volumes of PipeWire.")
        if snapshot.sound_server
        else Status("not connected", Tone.BAD, "The daemon waits for the sound server (PipeWire or PulseAudio).")
    )
    found = [
        Connection("Virtual device" if snapshot.virtual else device_name, "device", device, "device"),
        Connection("Sound server", "sound server", sound),
    ]
    if snapshot.mqtt is not None:
        found.append(Connection("Home Assistant", "Home Assistant", live_status(snapshot), "mqtt"))
    if snapshot.voip is not None:
        voip = snapshot.voip
        client = voip.client or voip.provider
        found.append(
            Connection(
                "Voice chat",
                "voice chat",
                Status(f"{client} · {voip.participants} in the call", Tone.GOOD, "The plugin of the voice chat client.")
                if voip.connected
                else Status(
                    "not connected",
                    Tone.NEUTRAL,
                    "No plugin of a voice chat client is connected: people show once one is (e.g. Mumble runs).",
                ),
                "voip",
            )
        )
    return tuple(found)


def worst(found: tuple[Connection, ...]) -> Connection | None:
    """The connection with the worst problem, None while all are fine (a voice chat not running is no problem)."""
    problems = [connection for connection in found if connection.status.tone in (Tone.BAD, Tone.WARN)]
    return min(problems, key=lambda connection: _ORDER.index(connection.status.tone), default=None)
