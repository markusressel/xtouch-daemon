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


@dataclass(frozen=True)
class Reason:
    """Why something can't be used: a few words to show next to it, and the whole of it."""

    short: str
    why: str


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
                "Live · not connected",
                Tone.WARN,
                f"The daemon runs but {device_name} is not there, so the strips are dark. Once it is, they light up.",
            )
        return Status("Live", Tone.GOOD, "The strips show what the device shows right now.")
    if daemon is None:
        return Status(
            "No daemon",
            Tone.WARN,
            "The daemon is not running, so the strips are dark: they show what the device shows, and only the daemon "
            "drives it. Install and start it with `xtouch-daemon install-service --now` (or run `xtouch-daemon run`), "
            "or try without a device.",
        )
    return Status(
        "No live view",
        Tone.WARN,
        f"The daemon (process {daemon.pid}) gives no live view; restart a daemon started before the live view "
        "existed. The strips are dark until it does.",
    )


def offers_virtual_device(snapshot: Snapshot | None, hosting: bool) -> bool:
    """Whether the GUI offers to open the virtual device: the daemon waits for it, and it doesn't run."""
    return snapshot is not None and snapshot.virtual and not snapshot.device and not hosting


class Switch(StrEnum):
    """How the GUI gets a daemon that drives the virtual device to the device that is plugged in."""

    FILE = "file"
    """`[device] virtual` is on in the file: turn it off and apply the file."""
    TRIAL = "trial"
    """The daemon is the window's own, to try without a device: end it, then start the service."""
    RESTART = "restart"
    """A daemon started with `--virtual-device` elsewhere: only a restart without it uses the device."""


@dataclass(frozen=True)
class DeviceOffer:
    """The device is plugged in while the daemon drives the virtual one: what the GUI says, and offers to do."""

    text: str
    action: str | None
    """The button that does it, None where the GUI can't (`Switch.RESTART`)."""
    switch: Switch


def device_offer(snapshot: Snapshot | None, device: str, file_virtual: bool, trying: bool) -> DeviceOffer | None:
    """
    What the GUI offers while the device `device` is plugged in and the daemon drives the virtual one; None otherwise.
    `file_virtual`: `[device] virtual` of the saved file; `trying`: the daemon is the window's, to try without a
    device.
    """
    if snapshot is None or not snapshot.virtual or not snapshot.device_plugged:
        return None
    text = f"{device} is plugged in, and the daemon drives the virtual device."
    if trying:
        return DeviceOffer(f"{text} End the trial, then start the service to use it.", "End the trial", Switch.TRIAL)
    if file_virtual:
        return DeviceOffer(text, "Switch to it", Switch.FILE)
    return DeviceOffer(
        f"{text} It runs with --virtual-device: start it without to use the device.", None, Switch.RESTART
    )


PLAY = "play"
"""The feature of the daemon (`Snapshot.features`) that a hand from the GUI needs."""


def play_unavailable(snapshot: Snapshot | None, owned: bool, hosting: bool, simulating: bool) -> Reason | None:
    """
    Why the mouse can't be a hand on the device, None when it can: on the virtual device the GUI hosts, or on the
    device of a daemon of this user that takes `Play` and has it connected. `simulating`: the drawing shows the virtual
    twin of the window (the preview in the GUI), which Play can always use (it needs the daemon anyway).
    """
    if simulating:
        return None
    if hosting:
        return None
    if snapshot is None:
        return Reason("no daemon", "No daemon runs: Try it without a device, or start the service.")
    if not owned:
        return Reason("another user's daemon", "The daemon runs as another user.")
    if PLAY not in snapshot.features:
        return Reason(
            "daemon too old",
            "The daemon that runs is too old to be played from here: restart it to run the installed version.",
        )
    if not snapshot.device:
        return Reason("device not connected", "The device is not connected.")
    return None


TEST = "test"
"""The feature of the daemon (`Snapshot.features`) that runs the test of the device (`StartTest`)."""


def test_unavailable(snapshot: Snapshot | None, owned: bool) -> Reason | None:
    """Why the daemon can't test the device now, None when it can."""
    if snapshot is None:
        return Reason("no daemon", "No daemon runs: start the service, or `xtouch-daemon test` without one.")
    if not owned:
        return Reason("another user's daemon", "The daemon runs as another user.")
    if TEST not in snapshot.features:
        return Reason(
            "daemon too old",
            "The daemon that runs is too old to test the device: restart it to run the installed version.",
        )
    if not snapshot.device:
        return Reason("device not connected", "The device is not connected.")
    return None


LOG = "log"
"""The feature of the daemon (`Snapshot.features`) that sends its log (`WatchLog`)."""


def log_unavailable(snapshot: Snapshot | None, owned: bool) -> Reason | None:
    """Why the window Log can't show the log of the daemon now, None when it can."""
    if snapshot is None:
        return Reason("no daemon", "No daemon runs: start the service to see its log.")
    if not owned:
        return Reason("another user's daemon", "The daemon runs as another user.")
    if LOG not in snapshot.features:
        return Reason(
            "daemon too old",
            "The daemon that runs is too old to show its log here: restart it to run the installed version.",
        )
    return None


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


def drawing_status(live: Status, in_gui: bool, on_device: bool) -> Status:
    """
    The pill of the drawing (`live`, see `preview_status()`) while it shows a preview of this window: on its twin
    (`in_gui`), or on the device (`on_device`).
    """
    if in_gui:
        return Status(
            "Preview in the GUI",
            Tone.NEUTRAL,
            "The strips show the preview on a twin of the device in the daemon: the changes, and Simulate while it is "
            "open. The device runs the saved file; Preview: Off shows it here.",
        )
    if on_device:
        return Status(
            f"{live.text} · preview", live.tone, f"{live.tip} The device runs the preview of this window, not the file."
        )
    return live


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
    simulated: bool = False,
    place: str = "device",
    what_if: bool = False,
) -> Status:
    """
    The pill next to Save and apply: whether the device runs the saved file, the unsaved changes (the live preview,
    "Preview: On the device"), or neither, in a few words, the rest in its tip. `applying` is true for a moment after a
    reload, which takes the daemon a moment; `previewed`: the device runs the document as it is; `trying`: the live
    preview is on; `problems`: the document has some, so it does not go to the device; `simulated`: the device shows
    the situation of Simulate. `place`: where the preview shows (a `live_preview.Place`); `what_if`: Simulate is open.
    """
    if place == "gui" and (modified or what_if):
        if modified and problems:
            return Status(
                "Paused: problems",
                Tone.WARN,
                "The changes have problems, so the preview keeps the last version without them. Fix them to go on.",
            )
        text = "In the GUI, not saved" if modified else "In the GUI"
        tip = (
            "The window shows the preview on a twin of the device; the device runs the saved file. Save and apply "
            "keeps the changes; Preview: On the device tries them there."
        )
        return Status(f"{text} · simulated" if what_if else text, Tone.NEUTRAL, tip)
    if place == "off" and modified:
        return Status(
            "Off: the device runs the file",
            Tone.NEUTRAL,
            "The changes show nowhere until you save them, or pick In the GUI or On the device for the preview.",
        )
    status = _changes_status(daemon, snapshot, path, saved, modified, applying, previewed, trying, problems)
    if not simulated:
        return status
    if status.text == "Sending to the device…":
        return status
    tip = "The device shows what Simulate shows, not what really happens: ending it (Esc) shows that again."
    if previewed:
        return Status(f"{status.text} · simulated", status.tone, f"{status.tip} {tip}")
    return Status("On the device · simulated", Tone.WARN, f"{tip} {status.tip}".strip())


def _changes_status(
    daemon: Instance | None,
    snapshot: Snapshot | None,
    path: Path,
    saved: Config | None,
    modified: bool,
    applying: bool,
    previewed: bool,
    trying: bool,
    problems: bool,
) -> Status:
    if previewed:
        return Status(
            "On the device, not saved",
            Tone.WARN,
            "The device runs the changes in the editor. Save and apply keeps them; another place for the preview, or "
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
            "The device runs the saved file. Preview: On the device runs the changes there before you save them.",
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
    Which unit the service has (its path is `state.unit`): the release package's, or one in the user's configuration,
    with the program it starts. `overrides`: that one hides the package's. None while it is not installed.
    """
    if state.unit is None:
        return None
    if state.packaged:
        return Status("packaged", Tone.NEUTRAL, "The unit of the package.")
    tip = "Your own unit"
    if state.program:
        tip += f", which starts `{state.program}`"
    tip += ". It overrides the unit of the package." if overrides else "."
    return Status("own unit", Tone.WARN if overrides else Tone.NEUTRAL, tip)


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
