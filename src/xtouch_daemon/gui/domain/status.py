"""
What the preview shows and whether the device runs what was saved: the GUI says it instead of leaving people to
guess whether a reload worked.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from xtouch_daemon.config import Config
from xtouch_daemon.instance import Instance
from xtouch_daemon.live import Snapshot, fingerprint


class Tone(StrEnum):
    GOOD = "good"
    WARN = "warn"
    BAD = "bad"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Status:
    text: str
    tone: Tone
    tip: str = ""


def preview_status(daemon: Instance | None, snapshot: Snapshot | None, device_name: str) -> Status:
    """Whether the preview shows the device live or only the file, and why."""
    if snapshot is not None:
        if not snapshot.device:
            return Status(
                f"Live · {device_name} not connected",
                Tone.WARN,
                "The daemon runs but the device is not there: the strips show what it will show once it is.",
            )
        return Status("Live", Tone.GOOD, "The strips show what the device shows right now.")
    if daemon is None:
        return Status(
            "File preview",
            Tone.NEUTRAL,
            "The daemon is not running: the strips show what the configuration would show.",
        )
    return Status(
        "File preview",
        Tone.NEUTRAL,
        f"No live view from the daemon (process {daemon.pid}); a restart of a daemon started before the live view "
        "existed gives one. The strips show what the configuration would show.",
    )


def sync_status(
    daemon: Instance | None,
    snapshot: Snapshot | None,
    path: Path,
    saved: Config | None,
    edited_strips: int,
    modified: bool,
    applying: bool,
) -> Status:
    """
    Whether the device runs the saved file, and what is not on it yet. `applying` is true for a moment after a
    reload, which takes the daemon a moment.
    """
    pending = ""
    if modified:
        pending = (
            f" {edited_strips} strip{'' if edited_strips == 1 else 's'} with unsaved changes show how they will look."
            if edited_strips
            else " There are unsaved changes."
        )
    if daemon is None:
        return Status(("Nothing runs this file." + pending).strip(), Tone.NEUTRAL)
    if path.resolve() != daemon.config:
        return Status(f"The daemon reads {daemon.config}, not this file.{pending}", Tone.WARN)
    if snapshot is None:
        return Status(("The daemon reads this file." + pending).strip(), Tone.NEUTRAL)
    if saved is not None and snapshot.config == fingerprint(saved):
        return Status(("The device runs the saved file." + pending).strip(), Tone.GOOD)
    if applying:
        return Status("Applying the saved file…", Tone.NEUTRAL)
    return Status(
        "The device does not run the saved file yet." + pending,
        Tone.WARN,
        "Save and apply it. If it stays like this, the daemon did not take the file: its log says why "
        "(journalctl --user -u xtouch-daemon), e.g. a changed [mqtt] section needs a restart.",
    )
