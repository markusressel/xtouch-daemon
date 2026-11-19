"""
The controls of the systemd user service in the header of the window.
"""

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QWidget

from xtouch_daemon import installed_version
from xtouch_daemon.gui.domain.connections import Connection, worst
from xtouch_daemon.gui.domain.status import Status, Tone, outdated, unit_status
from xtouch_daemon.gui.qt.fields.basics import label, show_status
from xtouch_daemon.gui.qt.fields.popover import Entry, show_popover
from xtouch_daemon.gui.qt.theme.style import set_role
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


class ServiceControls(QWidget):
    """
    The state of the systemd user service in a pill, which opens what can be done with it (restart, stop, use the
    unit of the package instead of one in ~/.config) and the connections of the daemon. What needs doing (install and
    start, start, restart after an upgrade) also has a button next to the pill.
    """

    settings_asked = pyqtSignal(str, arguments=["page"])
    """The list of the connections was asked for the settings of one (a page of the settings, e.g. "mqtt")."""
    changed = pyqtSignal(arguments=[])
    """The service was installed, started, stopped, ...: the window looks for the daemon again."""
    told = pyqtSignal(str, arguments=["text"])
    """What was done, for the status line."""

    def __init__(self, service: Service):
        super().__init__()
        self.service = service
        self.state: ServiceState | None = None
        """The state shown, None while it is not known (or the daemon runs outside the service)."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Service", "hint"))
        self.pill = label("…", "pill")
        self.pill.mousePressEvent = lambda event: self.show_details()  # type: ignore[method-assign]
        self.pill.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.service_status = Status("…", Tone.NEUTRAL)
        """The state of the service alone, without the connections of the daemon."""
        self.connections: tuple[Connection, ...] = ()
        self.unit: Status | None = None
        """Which unit is in effect: the package's, or one in ~/.config and the program it starts; None for none."""
        self.overrides = False
        """Whether a unit in ~/.config hides the one of the package."""
        self.service_button = QPushButton()
        """What the service needs (install and start, start, restart after an upgrade); in the popover always."""
        # a key typed into the window right after it opened must not install or start a service
        self.service_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.service_button.clicked.connect(self._service_action)
        layout.addWidget(self.service_button)

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
            self._no_service_controls()
            return
        try:
            state = self.service.state()
        except ServiceError as e:
            self.state = None
            self._show_service(Status("unavailable", Tone.BAD, str(e)))
            self._no_service_controls()
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
        self.service_button.setText(text)
        self.service_button.setToolTip(tip)
        set_role(self.service_button, "primary" if highlight else "", "variant")
        # a running service needs nothing, unless it runs an older version: Restart and Stop are in the popover
        self.service_button.setVisible(not state.running or highlight)
        self._show_service(Status(state.describe(), tone, f"`systemctl --user status {UNIT_NAME}` tells more."))

    def _show_service(self, status: Status) -> None:
        self.service_status = status
        self._show_pill()

    def show_connections(self, found: tuple[Connection, ...]) -> None:
        """What the daemon is connected to (see `domain.connections`): the pill tells the worst problem."""
        if found == self.connections:
            return
        self.connections = found
        self._show_pill()

    def _show_pill(self) -> None:
        """The state of the service, with the worst problem of a connection while it runs."""
        status = self.service_status
        problem = worst(self.connections)
        if problem is not None and status.tone == Tone.GOOD:
            status = Status(
                f"{status.text} · {problem.short} {problem.status.text}",
                problem.status.tone,
                f"{problem.status.tip}\n\n{status.tip}",
            )
        show_status(self.pill, status, more=True)

    def details(self) -> list[Entry]:
        """
        What the pill opens: the service with what can be done with it, its unit, and each connection of the daemon,
        how it is doing and why, with its settings.
        """
        state = self.state
        actions: tuple[tuple[str, Callable[[], object]], ...] = ()
        if state is not None:
            actions = ((self.service_button.text(), self._service_action),)
            if state.running:
                actions += (("Stop", self._stop),)
        service = self.service_status
        entries = [Entry("Service", service, actions=actions)]
        if state is not None and self.unit is not None:
            remove = (("Use the packaged unit", self._remove_override),) if self.overrides else ()
            entries.append(Entry("Unit", self.unit, path=str(state.unit), actions=remove))
        entries += [
            Entry(
                connection.name,
                connection.status,
                actions=(("Settings", lambda page=connection.settings: self.settings_asked.emit(page)),)
                if connection.settings is not None
                else (),
            )
            for connection in self.connections
        ]
        return entries

    def show_details(self) -> None:
        """Under the pill: the service, its unit and the connections of the daemon (see `details`)."""
        show_popover(self.pill, "Service", self.details())

    def _no_service_controls(self) -> None:
        self.unit = None
        self.overrides = False
        self.service_button.hide()

    def _service_action(self) -> None:
        state = self.state
        assert state is not None, "the button shows only with a known state"
        if not state.running:
            if state.installed:
                question = f"Enable {UNIT_NAME} (it starts with the session from now on) and start it?"
            elif uses_packaged_unit():
                question = f"Enable {UNIT_NAME} of the package (it starts with the session from now on) and start it?"
            else:
                question = f"Write {unit_path()}, then enable and start the service?"
            answer = QMessageBox.question(self.window(), "Service", question)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            if not state.installed:
                path = self.service.install(executable(), start=True)
                done = "Enabled the unit of the package" if path is None else f"Installed {path}"
                self.told.emit(f"{done} and started the service.")
            elif state.running:
                self.service.restart()
                self.told.emit("Restarted the service.")
            else:
                self.service.start()
                self.told.emit("Started the service.")
        except ServiceError as e:
            QMessageBox.warning(self.window(), "Service", str(e))
        self.changed.emit()

    def _remove_override(self) -> None:
        """Removes the unit in ~/.config, so the one of the package is in effect."""
        question = (
            f"Remove {unit_path()}? The unit of the package takes over; a running service restarts with the program "
            "of the package."
        )
        if QMessageBox.question(self.window(), "Service", question) != QMessageBox.StandardButton.Yes:
            return
        try:
            path = self.service.remove_override()
        except ServiceError as e:
            QMessageBox.warning(self.window(), "Service", str(e))
        else:
            self.told.emit(f"Removed {path}: the service uses the unit of the package.")
        self.changed.emit()

    def _stop(self) -> None:
        """Stops the service but leaves it enabled: Start (or the next session) brings it back."""
        try:
            self.service.stop()
        except ServiceError as e:
            QMessageBox.warning(self.window(), "Service", str(e))
        else:
            self.told.emit("Stopped the service.")
        self.changed.emit()
