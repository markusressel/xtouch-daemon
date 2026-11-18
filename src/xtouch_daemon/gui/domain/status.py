"""
What the preview shows and whether the device runs what was saved, which unit runs the service and whether it runs
the installed version: the GUI says it instead of leaving people to guess.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from xtouch_daemon.config.model import Config
from xtouch_daemon.live.messages import Snapshot, fingerprint
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import ServiceState


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


def preview_status(
    daemon: Instance | None, snapshot: Snapshot | None, device_name: str, hosting: bool = False
) -> Status:
    """
    Whether the preview shows the device live or only the file, and why. `hosting`: the GUI hosts the virtual device.
    """
    if snapshot is not None and snapshot.virtual:
        if snapshot.device:
            tip = "The mouse on the strips is a hand on it." if hosting else "It runs elsewhere (`virtual-device`)."
            return Status("Live · virtual device", Tone.GOOD, f"The strips show what the virtual device shows. {tip}")
        if hosting:
            return Status("Live · virtual device opening", Tone.NEUTRAL, "The daemon finds it within seconds.")
        return Status(
            "Live · virtual device not running · Open it",
            Tone.WARN,
            "The daemon drives the virtual device, which does not run: click to open it here, with the mouse on its "
            "strips (or run `xtouch-daemon virtual-device`).",
        )
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


def offers_virtual_device(snapshot: Snapshot | None, hosting: bool) -> bool:
    """Whether the GUI offers to open the virtual device: the daemon waits for it, and it doesn't run."""
    return snapshot is not None and snapshot.virtual and not snapshot.device and not hosting


def runs_older(daemon: Instance | None, snapshot: Snapshot | None, path: Path, saved: Config | None) -> bool:
    """
    Whether the daemon reads the file but runs another version of it, e.g. one changed outside the GUI or that it did
    not take: "Save and apply" then reloads it, also without changes to save.
    """
    return (
        daemon is not None
        and path.resolve() == daemon.config
        and snapshot is not None
        and not snapshot.preview
        and saved is not None
        and snapshot.config != fingerprint(saved)
    )


def changes_status(
    daemon: Instance | None,
    snapshot: Snapshot | None,
    path: Path,
    saved: Config | None,
    modified: bool,
    applying: bool,
    previewed: bool = False,
    trying: bool = False,
    problems: bool = False,
) -> Status:
    """
    The pill next to Save and apply: whether the device runs the saved file, the unsaved changes (the live preview,
    "Try on the device"), or neither, in a few words, the rest in its tip. `applying` is true for a moment after a
    reload, which takes the daemon a moment; `previewed`: the device runs the document as it is; `trying`: the live
    preview is on; `problems`: the document has some, so it does not go to the device.
    """
    if previewed:
        return Status(
            "On the device, not saved",
            Tone.WARN,
            "The device runs the changes in the editor. Save and apply keeps them; turning off Try on the device, or "
            "closing the window, brings back the saved file.",
        )
    if trying and modified and problems:
        return Status(
            "Paused: problems",
            Tone.WARN,
            "The changes have problems, so the device keeps the last version without them. Fix them to go on.",
        )
    if trying and modified:
        return Status("Sending to the device…", Tone.NEUTRAL, "The changes reach the device in a moment.")
    base = _saved_status(daemon, snapshot, path, saved, applying)
    if not modified:
        return base
    if base.tone == Tone.GOOD:
        return Status(
            "Unsaved changes",
            Tone.NEUTRAL,
            "The device runs the saved file. Try on the device runs the changes there before you save them.",
        )
    return Status("Unsaved changes", base.tone, f"{base.text}. {base.tip}".strip())


def _saved_status(
    daemon: Instance | None, snapshot: Snapshot | None, path: Path, saved: Config | None, applying: bool
) -> Status:
    """Whether the device runs the saved file, without the changes in the editor."""
    if daemon is None:
        return Status("Not running", Tone.NEUTRAL, "No daemon runs this file: start the service.")
    if path.resolve() != daemon.config:
        return Status("Runs another file", Tone.WARN, f"The daemon reads {daemon.config}, not this file.")
    if snapshot is None:
        return Status("Saved", Tone.NEUTRAL, "The daemon reads this file; it has no live view to tell what runs.")
    if saved is not None and snapshot.config == fingerprint(saved):
        return Status("Saved, on the device", Tone.GOOD, "The device runs the saved file.")
    if snapshot.preview:
        return Status(
            "Another window previews",
            Tone.WARN,
            "A window of the GUI tries unsaved changes on the device. The file runs again once that ends.",
        )
    if applying:
        return Status("Applying…", Tone.NEUTRAL, "The daemon loads the saved file.")
    return Status(
        "Not on the device yet",
        Tone.WARN,
        "Save and apply it. If it stays like this, the daemon did not take the file: its log says why "
        "(journalctl --user -u xtouch-daemon), e.g. a changed [mqtt] section needs a restart.",
    )


def unit_status(state: ServiceState, overrides: bool) -> Status | None:
    """
    Which unit the service has: the release package's, or one in the user's configuration, with the program it starts.
    `overrides`: that one hides the package's. None while it is not installed.
    """
    if state.unit is None:
        return None
    if state.packaged:
        return Status("packaged", Tone.NEUTRAL, f"The unit of the package: {state.unit}")
    tip = f"The unit {state.unit}"
    if overrides:
        tip += ", which overrides the one of the package"
    return Status(f"from {state.program or state.unit}", Tone.WARN if overrides else Tone.NEUTRAL, tip)


def outdated(state: ServiceState, snapshot: Snapshot | None, installed: str, program: str) -> str | None:
    """
    Why the service should restart: it runs another version than the one installed (e.g. after an upgrade of the
    package). Only for the service of `program`, the installation the GUI runs from, whose version is `installed`.
    None when it runs the installed version, or the daemon does not tell its version.
    """
    if not state.running or state.program != program or snapshot is None or snapshot.daemon_version is None:
        return None
    if snapshot.daemon_version == installed:
        return None
    return f"The daemon runs version {snapshot.daemon_version}, {installed} is installed: restart it to run {installed}"
