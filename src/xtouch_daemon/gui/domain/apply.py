"""Applying a saved configuration: reloading the daemon when it runs as the service and reads the file."""

from dataclasses import dataclass
from pathlib import Path

from xtouch_daemon.config import default_config_path
from xtouch_daemon.systemd import Service


@dataclass(frozen=True)
class Applied:
    message: str
    reloaded: bool
    restart_needed: bool = False
    """The daemon reloaded, but the `[device]` section changed, which takes a restart."""


def apply(service: Service, path: Path, device_changed: bool) -> Applied:
    """Reloads the service after `path` was saved, if it runs and reads that file."""
    default = default_config_path()
    if path.resolve() != default.resolve():
        return Applied(f"Saved. The service reads {default}, not this file, so it was not reloaded.", reloaded=False)
    state = service.state()
    if not state.running:
        return Applied(f"Saved. The service is {state.describe()}: start it to use the configuration.", reloaded=False)
    service.reload()
    if device_changed:
        return Applied(
            "Saved and reloaded. The [device] section changed: restart the service for that to take effect.",
            reloaded=True,
            restart_needed=True,
        )
    return Applied("Saved and reloaded: the device shows the new configuration.", reloaded=True)
