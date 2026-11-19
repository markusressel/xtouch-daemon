"""
The virtual twin of the window (see `docs/development/design/previews.md`): where the preview shows in the GUI, and
Simulate with it. Here: whether it can be asked for.
"""

from xtouch_daemon.gui.domain.status import Reason
from xtouch_daemon.live.messages import Snapshot

FEATURE = "on_device"
"""The feature of the daemon (`Snapshot.features`) that a twin needs."""


def unavailable(snapshot: Snapshot | None, owned: bool) -> Reason | None:
    """
    Why the preview can't show in the GUI (and Simulate can't run), None when it can: a daemon has to tell what it
    shows (`snapshot`), run as this user (the configuration, with its secrets, goes to it, `owned`, see
    `LiveView.owned`) and know twins. Any daemon of this user will do, also one that reads another file.
    """
    if snapshot is None:
        return Reason(
            "no daemon",
            "The preview runs on a virtual twin in the daemon, and no daemon runs: start the service "
            "(`xtouch-daemon install-service --now`), or try without a device.",
        )
    if not owned:
        return Reason(
            "another user's daemon",
            "The daemon runs as another user: the configuration, with its secrets, does not go to it.",
        )
    if FEATURE not in snapshot.features:
        return Reason(
            "daemon too old",
            "The daemon that runs is too old for the preview: restart it to run the installed version.",
        )
    return None
