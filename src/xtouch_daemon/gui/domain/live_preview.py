"""
The live preview: while it is on, the daemon runs the configuration in the editor instead of the file (see
`live.StartPreview`), so the device follows every edit before it is saved. Here: whether it can be turned on, and what
the window says about it.
"""

from pathlib import Path

from xtouch_daemon.config.model import Config
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.instance import Instance
from xtouch_daemon.live.messages import Snapshot, fingerprint

FEATURE = "preview"
"""The feature of the daemon (`Snapshot.features`) that the live preview needs."""


def unavailable(daemon: Instance | None, snapshot: Snapshot | None, path: Path, owned: bool) -> str | None:
    """
    Why the live preview can't be turned on, None when it can: a daemon has to run this file, tell what the device
    shows (`snapshot`), run as this user (`owned`, see `LiveView.owned`) and know previews.
    """
    if daemon is None:
        return "No daemon runs: start the service to preview the changes on the device."
    if path.resolve() != daemon.config:
        return f"The daemon runs {daemon.config}, not this file."
    if snapshot is None:
        return f"No live view from the daemon (process {daemon.pid}): restart it for a live preview."
    if not owned:
        return "The daemon runs as another user: the configuration, with its secrets, does not go to it."
    if FEATURE not in snapshot.features:
        return "The daemon that runs is too old for a live preview: restart it to run the installed version."
    return None


def previewed(snapshot: Snapshot | None, config: Config | None, running: bool) -> bool:
    """
    Whether the device shows the document as it is now: our preview runs (`running`) and the daemon uses `config`,
    the configuration of the document (None while it has problems).
    """
    return (
        running
        and snapshot is not None
        and snapshot.preview
        and config is not None
        and snapshot.config == fingerprint(config)
    )


def preview_pill(on: bool, running: bool, modified: bool, problems: bool) -> Status | None:
    """
    What the pill of the live preview says; None while it is off. `running`: the daemon runs a preview of this window,
    `problems`: the document has some, so it does not go to the daemon.
    """
    if not on:
        return None
    if modified and problems:
        return Status(
            "Live preview paused",
            Tone.WARN,
            "The configuration has problems: the device keeps the last version without them. Fix them to go on.",
        )
    if running:
        return Status(
            "Previewing unsaved changes",
            Tone.WARN,
            "The device runs the configuration in the editor, not the file. Save to keep it, turn the live preview "
            "off (or close the window) to go back to the file.",
        )
    if modified:
        return Status("Live preview…", Tone.NEUTRAL, "The changes go to the device in a moment.")
    return Status(
        "Live preview",
        Tone.NEUTRAL,
        "No unsaved changes: the device runs the file. The next change goes to the device right away.",
    )
