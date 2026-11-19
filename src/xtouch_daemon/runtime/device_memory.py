"""
The devices the daemon saw, kept in its state directory (`devices.json`), so the GUI can suggest a device for a
configuration while it is not there: Bluetooth headphones that are off, a USB headset that is unplugged, the digital
output while its card is in the analog profile. A device not seen for FORGET_AFTER is forgotten. Errors are logged,
never raised: the daemon runs on without them.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path

from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.live.messages import KnownDevice, KnownDevices

_LOGGER = logging.getLogger(__name__)

DEVICES_FILE_NAME = "devices.json"
"""The file of the devices seen, in the state directory of the daemon."""
FORGET_AFTER = 90 * 24 * 3600.0
"""A device not seen for this long (in seconds) is forgotten."""
TOUCH_INTERVAL = 3600.0
"""How often (in seconds) the time a device that stays was seen last is kept: not at every change of its volume."""


class DeviceMemory:
    """
    The devices seen (see `KnownDevice`), by direction and name; `path` is where they are kept (None: nowhere),
    `wall_clock` tells the time in seconds since the epoch.
    """

    def __init__(self, path: Path | None, wall_clock: Callable[[], float] = time.time):
        self.path = path
        self._wall_clock = wall_clock
        self.devices: dict[tuple[str, str], KnownDevice] = {}
        if path is not None:
            self.devices = {(device.direction, device.name): device for device in _read(path)}
        self._expire(wall_clock())

    def known(self) -> KnownDevices:
        """Every device remembered, outputs first, by description."""
        return KnownDevices(
            tuple(sorted(self.devices.values(), key=lambda d: (d.direction != "output", d.description)))
        )

    def see(self, state: AudioState) -> bool:
        """
        The devices the sound server has now are seen: new ones are remembered, what changed of known ones is kept.
        Whether the devices remembered changed (a time last seen alone counts only every TOUCH_INTERVAL).
        """
        if not state.connected:
            return False
        now = self._wall_clock()
        changed = False
        for device in (*state.outputs, *state.inputs):
            card = state.card(device.card)
            seen = KnownDevice(
                device.name,
                device.description,
                device.direction.value,
                device.card,
                card.profile if card is not None else None,
                now,
            )
            key = (seen.direction, seen.name)
            before = self.devices.get(key)
            if before is not None and replace(before, seen=now) == seen and now - before.seen < TOUCH_INTERVAL:
                continue
            self.devices[key] = seen
            changed = True
        changed = self._expire(now) or changed
        if changed:
            self._write()
        return changed

    def forget(self, name: str, direction: str) -> bool:
        """Forgets a device; whether it was remembered."""
        if self.devices.pop((direction, name), None) is None:
            return False
        self._write()
        return True

    def _expire(self, now: float) -> bool:
        old = [key for key, device in self.devices.items() if now - device.seen > FORGET_AFTER]
        for key in old:
            del self.devices[key]
        return bool(old)

    def _write(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # whole or not at all
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            data = [asdict(device) for device in self.known().devices]
            temporary.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError as e:
            _LOGGER.warning(f"Can't keep the devices seen in {self.path}: {e}")


def _read(path: Path) -> list[KnownDevice]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            KnownDevice(
                str(entry["name"]),
                str(entry["description"]),
                str(entry["direction"]),
                None if entry["card"] is None else str(entry["card"]),
                None if entry["profile"] is None else str(entry["profile"]),
                float(entry["seen"]),
            )
            for entry in data
        ]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError, TypeError) as e:
        _LOGGER.warning(f"Can't read the devices seen from {path}: {e}")
        return []
