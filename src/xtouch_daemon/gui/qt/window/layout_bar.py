"""
The layouts of the file above the strips: one tab each, the one the device shows marked; + adds one, and one button
shows the edited one on the device.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QTabBar, QToolButton, QWidget

from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.qt.fields.basics import label
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.live.messages import Snapshot

ACTIVE_MARK = " ●"
"""Next to the name of the layout the device shows."""


class LayoutBar(QWidget):
    picked = pyqtSignal(object, arguments=["index"])
    """A layout was picked to edit: an index of the layouts of the document, None for the default one."""
    add = pyqtSignal(bool, arguments=["copy_strips"])
    """Add a layout: a copy of the edited one (True), or one of `auto` strips."""
    show_on_device = pyqtSignal(arguments=[])
    """Switch the running daemon to the edited layout."""

    def __init__(self):
        super().__init__()
        self._shown: object = None
        """What the tabs show, so that they are filled again only when that changes."""
        bar = QHBoxLayout(self)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(label("Layout", "hint"))
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setToolTip(f"The layouts of the file; {ACTIVE_MARK.strip()} marks the one the device shows")
        self.tabs.currentChanged.connect(lambda index: self.picked.emit(None if index <= 0 else index - 1))
        bar.addWidget(self.tabs)
        self.add_button = QToolButton()
        set_icon(self.add_button, "plus")
        self.add_button.setToolTip("Add a layout")
        self.add_button.setAutoRaise(True)
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.add_button)
        empty = menu.addAction("Empty layout (auto strips)")
        assert empty is not None
        empty.triggered.connect(lambda: self.add.emit(False))
        copied = menu.addAction("Copy of this layout")
        assert copied is not None
        copied.triggered.connect(lambda: self.add.emit(True))
        self.add_button.setMenu(menu)
        bar.addWidget(self.add_button)
        bar.addStretch()
        self.show_button = QPushButton("Show on the device")
        self.show_button.setToolTip(
            "Switch the running daemon to this layout (as saved, or as previewed while the live preview runs)"
        )
        self.show_button.clicked.connect(self.show_on_device)
        bar.addWidget(self.show_button)

    def show_layouts(self, document: ConfigDocument, snapshot: Snapshot | None) -> None:
        """
        Fills the tabs again when they show something else: after a layout was added, removed, renamed or moved,
        another one is edited, or the device shows another one.
        """
        active = (snapshot.layout or "default") if snapshot is not None else None
        names = document.layout_names
        shown = (tuple(names), document.layout, active, snapshot is not None and tuple(snapshot.layouts))
        if shown == self._shown:
            return
        self._shown = shown
        self.tabs.blockSignals(True)
        while self.tabs.count() > len(names):
            self.tabs.removeTab(self.tabs.count() - 1)
        for index, name in enumerate(names):
            text = (name or "(no name)") + (ACTIVE_MARK if name == active else "")
            if index < self.tabs.count():
                self.tabs.setTabText(index, text)
            else:
                self.tabs.addTab(text)
        edited = document.layout
        self.tabs.setCurrentIndex(0 if edited is None else edited + 1)
        self.tabs.blockSignals(False)
        showable = snapshot is not None and active != document.layout_name
        self.show_button.setVisible(bool(document.layouts))
        self.show_button.setEnabled(showable and snapshot is not None and document.layout_name in snapshot.layouts)
