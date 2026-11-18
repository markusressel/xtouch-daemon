"""Applying a saved configuration: reloading the running daemon when it reads the file."""

from dataclasses import dataclass
from pathlib import Path

from xtouch_daemon.system.instance import Instance


@dataclass(frozen=True)
class Applied:
    message: str
    reloaded: bool
    restart_needed: bool = False
    """A section changed that the daemon takes only with a restart."""


def describe(instance: Instance) -> str:
    return "the service" if instance.systemd else f"the daemon (process {instance.pid})"


def apply(instance: Instance | None, path: Path, restart_sections: tuple[str, ...] = ()) -> Applied:
    """
    Reloads the running daemon (`instance`, the service or one started elsewhere, e.g. from an IDE) after `path` was
    saved, if it reads that file. `restart_sections` are the changed sections a reload does not take: the daemon keeps
    the whole old configuration when `[mqtt]` changed, so that is not reloaded at all.
    """
    if instance is None:
        return Applied("Saved. The daemon is not running: start it to use the configuration.", reloaded=False)
    daemon = describe(instance)
    if path.resolve() != instance.config:
        return Applied(f"Saved. {daemon.capitalize()} reads {instance.config}, not this file.", reloaded=False)
    if "mqtt" in restart_sections:
        return Applied(
            f"Saved. The [mqtt] section changed: restart {daemon} to use the configuration.",
            reloaded=False,
            restart_needed=True,
        )
    instance.reload()
    return Applied("Saved and reloaded: the device shows the new configuration.", reloaded=True)
