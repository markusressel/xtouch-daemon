"""
The navigation of the window Configuration: the rail of its pages on the left, and the navigation of the settings.
"""

from collections.abc import Mapping

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.qt.pages.base import (
    SETTINGS_GROUPS,
    SETTINGS_NAV,
    Page,
    page_title,
    scrolled,
    settings_entry,
)
from xtouch_daemon.gui.qt.theme.icons import set_icon
from xtouch_daemon.gui.qt.theme.settings import load_rail_labels, save_rail_labels
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space

RAIL = (
    ("slots", "Slots", "tune-vertical", "What each slot shows when"),
    ("channels", "Channels", "format-list-bulleted", "What a strip can control"),
    ("states", "States", "toggle-switch-outline", "The states and modes that decide what slots show"),
    ("settings", "Settings", "cog-outline", "The device, behavior, aliases, Home Assistant, the voice chat"),
)
"""The pages of the rail: name, title, icon, tip."""
RAIL_PAGES = tuple(name for name, *_ in RAIL)
"""The names of the pages of the rail, in their order: Ctrl+1 shows the first one."""
RAIL_TITLES = tuple(title for _, title, *_ in RAIL)
RAIL_ICON = 22
"""The size of the icons of the rail without their names."""


class Rail(QWidget):
    """
    The pages on the left of the window Configuration, one at a time: icons, with their names under them once the
    button at the foot shows them (remembered).
    """

    picked = pyqtSignal(str, arguments=["page"])
    """A page of the rail was clicked."""

    def __init__(self) -> None:
        super().__init__()
        set_role(self, "rail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Space.XS, Space.M, Space.XS, Space.M)
        layout.setSpacing(Space.XS)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QToolButton] = {}
        for number, (name, title, icon_name, tip) in enumerate(RAIL, start=1):
            rail_button = QToolButton()
            rail_button.setText(title)
            # the pages of the states, channels and slots in their colors, like everywhere in the window
            set_icon(rail_button, icon_name, name.removesuffix("s") if name != "settings" else None)
            rail_button.setCheckable(True)
            rail_button.setAutoRaise(True)
            rail_button.setToolTip(f"{title}: {tip} (Ctrl+{number})")
            rail_button.clicked.connect(lambda _=False, name=name: self.picked.emit(name))
            self.group.addButton(rail_button)
            self.buttons[name] = rail_button
            layout.addWidget(rail_button)
        self.icon_size = self.buttons["slots"].iconSize()
        """The size of the icons with their names under them (the style's)."""
        layout.addStretch()
        self.labels_button = QToolButton()
        self.labels_button.setAutoRaise(True)
        self.labels_button.clicked.connect(lambda: self.show_labels(not load_rail_labels()))
        layout.addWidget(self.labels_button)
        self.show_labels(load_rail_labels())

    def show_labels(self, shown: bool) -> None:
        """The names of the pages under their icons, or icons only."""
        save_rail_labels(shown)
        for rail_button in self.buttons.values():
            if shown:
                rail_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                rail_button.setMinimumWidth(72)
            else:
                rail_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                rail_button.setMinimumWidth(0)
            # alone, the icon is the target: as large as with its name
            rail_button.setIconSize(self.icon_size if shown else QSize(RAIL_ICON, RAIL_ICON))
        set_icon(self.labels_button, "chevron-double-left" if shown else "chevron-double-right")
        self.labels_button.setToolTip("Hide the names of the pages" if shown else "Show the names of the pages")


class SettingsPages(QWidget):
    """
    The sections with options of their own (`SETTINGS_PAGES`), one entry of the navigation on the left at a time;
    the sections of a group (`SETTINGS_GROUPS`) share one, one below the other.
    """

    picked = pyqtSignal(str, arguments=["page"])
    """A section of the navigation was clicked."""

    def __init__(self, pages: Mapping[str, Page]):
        super().__init__()
        self.pages = pages
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, Space.M, 0, 0)
        layout.setSpacing(16)
        nav = QVBoxLayout()
        nav.setSpacing(2)
        self.group = QButtonGroup(self)
        self.stack = QStackedWidget()
        self.buttons: dict[str, QPushButton] = {}
        self.scrolls: dict[str, QScrollArea] = {}
        self.section = SETTINGS_NAV[0]
        """The section shown last: the first of its entry, or the one `show_page` scrolled to."""
        for name in SETTINGS_NAV:
            sections = SETTINGS_GROUPS.get(name, (name,))
            nav_button = QPushButton(page_title(name))
            set_role(nav_button, "nav", "variant")
            nav_button.setCheckable(True)
            nav_button.setToolTip(" and ".join(f"[{section}]" for section in sections) + " in the file")
            nav_button.clicked.connect(lambda _=False, name=name: self.picked.emit(name))
            self.group.addButton(nav_button)
            self.buttons[name] = nav_button
            nav.addWidget(nav_button)
            self.scrolls[name] = scrolled(pages[name] if len(sections) == 1 else self._together(sections))
            self.stack.addWidget(self.scrolls[name])
        nav.addStretch()
        holder = QWidget()
        holder.setLayout(nav)
        nav.setContentsMargins(0, 0, 0, 0)
        # wide enough for the longest name with the padding of the style
        holder.setMinimumWidth(max(nav_button.sizeHint().width() for nav_button in self.buttons.values()) + 40)
        layout.addWidget(holder)
        layout.addWidget(self.stack, 1)
        self.buttons[SETTINGS_NAV[0]].setChecked(True)

    def _together(self, sections: tuple[str, ...]) -> QWidget:
        """The pages of `sections`, one below the other."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.XL)
        for section in sections:
            layout.addWidget(self.pages[section])
        layout.addStretch()
        return widget

    def show_page(self, name: str) -> None:
        """Shows the section `name`: its entry, scrolled to it if it shares the page."""
        entry = settings_entry(name)
        self.section = name
        self.buttons[entry].setChecked(True)
        self.stack.setCurrentIndex(SETTINGS_NAV.index(entry))
        self._scroll_to(name)
        # a page shown for the first time has its place only once the event loop laid it out
        QTimer.singleShot(0, lambda: self._scroll_to(name))

    def _scroll_to(self, name: str) -> None:
        scroll = self.scrolls[settings_entry(name)].verticalScrollBar()
        if scroll is not None and self.section == name:
            scroll.setValue(0 if name == settings_entry(name) else self.pages[name].y())

    @property
    def current_page(self) -> str:
        return self.section
