"""
The live preview: while it is on, the daemon runs the configuration in the editor instead of the file (see
`live.StartPreview`), so the device follows every edit before it is saved. Here: whether it can be turned on, and what
the window says about it.
"""

from pathlib import Path

from xtouch_daemon.config.model import Config
from xtouch_daemon.gui.domain.status import Reason
from xtouch_daemon.live.messages import Snapshot, fingerprint
from xtouch_daemon.system.instance import Instance

FEATURE = "preview"
"""The feature of the daemon (`Snapshot.features`) that the live preview needs."""


def unavailable(daemon: Instance | None, snapshot: Snapshot | None, path: Path, owned: bool) -> Reason | None:
    """
    Why the live preview can't be turned on, None when it can: a daemon has to run this file, tell what the device
    shows (`snapshot`), run as this user (`owned`, see `LiveView.owned`) and know previews.
    """
    if daemon is None:
        return Reason("no daemon", "No daemon runs: start the service to try the changes on the device.")
    if path.resolve() != daemon.config:
        return Reason("the daemon runs another file", f"The daemon runs {daemon.config}, not this file.")
    if snapshot is None:
        return Reason(
            "no live view",
            f"No live view from the daemon (process {daemon.pid}): restart it to try changes on the device.",
        )
    if not owned:
        return Reason(
            "another user's daemon",
            "The daemon runs as another user: the configuration, with its secrets, does not go to it.",
        )
    if FEATURE not in snapshot.features:
        return Reason(
            "daemon too old",
            "The daemon that runs is too old to try changes on the device: restart it to run the installed version.",
        )
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
