"""
The systemd user service at the right end of the menu bar: its state in a pill (a click opens what can be done with it
and the connections of the daemon), and a button for what it needs (install and start, start, restart after an upgrade).
"""

from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon import installed_version
from xtouch_daemon.gui.domain.connections import Connection, worst
from xtouch_daemon.gui.domain.status import Status, Tone, outdated, unit_status
from xtouch_daemon.gui.quick.details import Content, Details, Entry
from xtouch_daemon.gui.quick.window.dialogs import YES, YES_NO, Asker
from xtouch_daemon.gui.quick.window.rich import Rich
from xtouch_daemon.live.messages import Snapshot
from xtouch_daemon.system.instance import Instance
from xtouch_daemon.system.systemd import (
    UNIT_NAME,
    Service,
    ServiceError,
    ServiceState,
    executable,
    overrides_packaged_unit,
    unit_path,
    uses_packaged_unit,
)

PILL_FIRST = "…"


class ServiceBackend(QObject):
    """See the module."""

    shown = pyqtSignal(arguments=[])
    settingsAsked = pyqtSignal(str, arguments=["page"])
    """The list of the connections was asked for the settings of one (a page of the settings, e.g. "mqtt")."""
    changed = pyqtSignal(arguments=[])
    """The service was installed, started, stopped, ...: the window looks for the daemon again."""
    told = pyqtSignal(str, arguments=["text"])
    """What was done, for the status line."""

    def __init__(self, service: Service, asker: Asker, rich: Rich, parent: QObject | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.service = service
        self.asker = asker
        self.state: ServiceState | None = None
        """The state shown, None while it is not known (or the daemon runs outside the service)."""
        self.service_status = Status(PILL_FIRST, Tone.NEUTRAL)
        """The state of the service alone, without the connections of the daemon."""
        self.connections: tuple[Connection, ...] = ()
        self.unit: Status | None = None
        """Which unit is in effect: the package's, or one in ~/.config and the program it starts; None for none."""
        self.overrides = False
        """Whether a unit in ~/.config hides the one of the package."""
        self.button_text = ""
        self.button_tip = ""
        self.button_visible = False
        self.button_highlight = False
        self.details = Details(self._content, rich, self)

    # -- what QML shows -------------------------------------------------------------------------------------------

    def _pill(self) -> Status:
        """The state of the service, with the worst problem of a connection while it runs."""
        status = self.service_status
        problem = worst(self.connections)
        if problem is not None and status.tone == Tone.GOOD:
            return Status(
                f"{status.text} · {problem.short} {problem.status.text}",
                problem.status.tone,
                f"{problem.status.tip}\n\n{status.tip}",
            )
        return status

    @pyqtProperty(str, notify=shown)
    def pillText(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._pill().text

    @pyqtProperty(str, notify=shown)
    def pillTone(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self._pill().tone.value

    @pyqtProperty(str, notify=shown)
    def pillTip(self) -> str:  # pyright: ignore[reportRedeclaration]
        return f"{self._pill().tip.split(chr(10) * 2)[0]}\n\nClick for details."

    @pyqtProperty(str, notify=shown)
    def buttonLabel(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self.button_text

    @pyqtProperty(str, notify=shown)
    def buttonHint(self) -> str:  # pyright: ignore[reportRedeclaration]
        return self.button_tip

    @pyqtProperty(bool, notify=shown)
    def buttonShown(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.button_visible

    @pyqtProperty(bool, notify=shown)
    def buttonPrimary(self) -> bool:  # pyright: ignore[reportRedeclaration]
        return self.button_highlight

    @pyqtProperty(QObject, constant=True)
    def popover(self) -> QObject:  # pyright: ignore[reportRedeclaration]
        return self.details

    # -- the state ------------------------------------------------------------------------------------------------

    def show_state(self, daemon: Instance | None, snapshot: Snapshot | None) -> None:
        """Shows the state of the service, or of the daemon `daemon` that runs outside of it."""
        if daemon is not None and not daemon.systemd:
            # started from a terminal or an IDE: the service can't start (the device is taken) or restart it
            self.state = None
            tip = (
                f"The daemon runs outside systemd (process {daemon.pid}, e.g. from a terminal or an IDE) "
                f"and reads {daemon.config}. Saving reloads it; restart it where it runs."
            )
            self._show_service(Status("running elsewhere", Tone.GOOD, tip))
            self._no_controls()
            return
        try:
            state = self.service.state()
        except ServiceError as e:
            self.state = None
            self._show_service(Status("unavailable", Tone.BAD, str(e)))
            self._no_controls()
            return
        self.state = state
        highlight = False
        if not state.installed:
            tone, text = Tone.WARN, "Install and start"
            tip = (
                "Enable the unit of the package and start it"
                if uses_packaged_unit()
                else "Write the systemd user unit, enable and start it"
            )
        elif state.running:
            tone, text, tip = Tone.GOOD, "Restart", "Restart the daemon, e.g. after changing the device name"
            reason = outdated(state, snapshot, installed_version(), executable())
            if reason is not None:
                highlight, tip = True, reason
        else:
            tone = Tone.BAD if state.active == "failed" else Tone.NEUTRAL
            text, tip = "Start", "Enable the service and start it"
        self.overrides = overrides_packaged_unit()
        self.unit = unit_status(state, self.overrides)
        self.button_text, self.button_tip, self.button_highlight = text, tip, highlight
        # a running service needs nothing, unless it runs an older version: Restart and Stop are in the popover
        self.button_visible = not state.running or highlight
        self._show_service(Status(state.describe(), tone, f"`systemctl --user status {UNIT_NAME}` tells more."))

    def _show_service(self, status: Status) -> None:
        self.service_status = status
        self._shown()

    def show_connections(self, found: tuple[Connection, ...]) -> None:
        """What the daemon is connected to (see `domain.connections`): the pill tells the worst problem."""
        if found != self.connections:
            self.connections = found
            self._shown()

    def _shown(self) -> None:
        self.shown.emit()
        self.details.refresh_if_open()

    def _no_controls(self) -> None:
        self.unit = None
        self.overrides = False
        self.button_visible = False
        self.shown.emit()

    def _content(self) -> Content:
        """
        What the pill opens: the service with what can be done with it, its unit, and each connection of the daemon,
        how it is doing and why, with its settings.
        """
        state = self.state
        actions: tuple[tuple[str, Callable[[], object]], ...] = ()
        if state is not None:
            actions = ((self.button_text, self.act),)
            if state.running:
                actions += (("Stop", self.stop),)
        entries = [Entry("Service", self.service_status, actions=actions)]
        if state is not None and self.unit is not None:
            remove = (("Use the packaged unit", self.remove_override),) if self.overrides else ()
            entries.append(Entry("Unit", self.unit, path=str(state.unit), actions=remove))
        entries += [
            Entry(
                connection.name,
                connection.status,
                actions=(("Settings", lambda page=connection.settings: self.settingsAsked.emit(page)),)
                if connection.settings is not None
                else (),
            )
            for connection in self.connections
        ]
        return Content("Service", entries)

    # -- what can be done -----------------------------------------------------------------------------------------

    @pyqtSlot()
    def act(self) -> None:
        """The button: install and start, start, or restart (after a question where it changes what runs)."""
        state = self.state
        if state is None:
            return
        if not state.running:
            if state.installed:
                question = f"Enable {UNIT_NAME} (it starts with the session from now on) and start it?"
            elif uses_packaged_unit():
                question = f"Enable {UNIT_NAME} of the package (it starts with the session from now on) and start it?"
            else:
                question = f"Write {unit_path()}, then enable and start the service?"
            if self.asker.ask("Service", question, YES_NO) != YES:
                return
        try:
            if not state.installed:
                path = self.service.install(executable(), start=True)
                done = "Enabled the unit of the package" if path is None else f"Installed {path}"
                self.told.emit(f"{done}; starting the service…")
            elif state.running:
                self.service.restart()
                self.told.emit("Restarting the service…")
            else:
                self.service.start()
                self.told.emit("Starting the service…")
        except ServiceError as e:
            self.asker.tell("Service", str(e))
        self.changed.emit()

    def remove_override(self) -> None:
        """Removes the unit in ~/.config, so the one of the package is in effect."""
        question = (
            f"Remove {unit_path()}? The unit of the package takes over; a running service restarts with the program "
            "of the package."
        )
        if self.asker.ask("Service", question, YES_NO) != YES:
            return
        try:
            path = self.service.remove_override()
        except ServiceError as e:
            self.asker.tell("Service", str(e))
        else:
            self.told.emit(f"Removed {path}: the service uses the unit of the package.")
        self.changed.emit()

    def stop(self) -> None:
        """Stops the service but leaves it enabled: Start (or the next session) brings it back."""
        try:
            self.service.stop()
        except ServiceError as e:
            self.asker.tell("Service", str(e))
        else:
            self.told.emit("Stopping the service…")
        self.changed.emit()
