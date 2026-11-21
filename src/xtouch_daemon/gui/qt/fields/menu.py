"""
Menus that open inside the window. A `QMenu` is a popup window: it grabs the keyboard and the mouse (on X11 the whole
display), so the key of a screenshot tool or of the window manager does nothing while it is open, and Alt closes it.

The menus stay `QMenu`s, built as usual (actions with icons, checks and shortcuts, separators, sections, submenus), but
are never shown: `show_menu` draws one as a popover in its window, `attach_menu` opens one from a button, and `MenuBar`
is a menu bar whose menus open that way. Their shortcuts work as before, the window's.

An action can say more than its text (`describe`): a line under it, and the color of what it adds (a channel, a
state). A menu with such actions is a rich one: its rows have room for the line, which wraps.
"""

import re
from collections.abc import Callable

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QSize, Qt
from PyQt6.QtGui import QAction, QContextMenuEvent, QHideEvent, QIcon, QKeyEvent, QMouseEvent, QShowEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.gui.qt.app_events import app_events
from xtouch_daemon.gui.qt.fields.basics import help_text
from xtouch_daemon.gui.qt.fields.depth import lift
from xtouch_daemon.gui.qt.fields.popover import Popover, place
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import current_colors, set_role
from xtouch_daemon.gui.qt.theme.tokens import Entity, Space

DETAIL = "menu_detail"
"""The property of an action with the line under its text (see `describe`)."""
ENTITY = "menu_entity"
"""The property of an action with what its text names, in its color (see `describe`)."""
ICON_NAME = "menu_icon"
"""The property of an action with the name of its icon (see `with_icon`)."""
RICH_WIDTH = 340
"""The width of the lines under the texts of a rich menu: they wrap at it."""
ICON = 16
"""The size of the icons of a menu, and of the check marks."""
RICH_ICON = 20
"""The size of the icons of a rich menu."""
_MNEMONIC = re.compile(r"&(.)")


def describe(action: QAction, detail: str, entity: Entity | None = None) -> QAction:
    """
    Gives `action` a line under its text, what it does (with `code` and the words for states and channels in their
    colors, as the help), and the color of what it names (`entity`), for a rich menu.
    """
    action.setProperty(DETAIL, detail)
    if entity is not None:
        action.setProperty(ENTITY, entity.value)
    return action


def with_icon(action: QAction, name: str) -> QAction:
    """
    Gives `action` an icon (see `icon()`) that follows the theme: drawn in its colors whenever the menu opens, unlike
    an icon of the action itself, which keeps the colors of the theme it was made in.
    """
    action.setProperty(ICON_NAME, name)
    action.setIcon(icon(name))
    return action


def plain(text: str) -> str:
    """The text of an action without its `&` (`&&` is an `&`)."""
    return _MNEMONIC.sub(r"\1", text)


def mnemonic(text: str) -> str:
    """The key of an action, after its `&`, in lower case; "" for none."""
    for match in _MNEMONIC.finditer(text):
        if match[1] != "&":
            return match[1].lower()
    return ""


def show_menu(
    menu: QMenu,
    anchor: QWidget,
    at: QPoint | None = None,
    side: Callable[[int], None] | None = None,
) -> MenuPanel | None:
    """
    Shows `menu` in the window of `anchor`: under it (above where there is no room below), or at `at` (a point of the
    screen, e.g. of a right click). `side` is for the menus of a menu bar: Left and Right go to the menu before (-1) or
    after (1). Nothing opens for an anchor without a window of its own.
    """
    window = anchor.window()
    if window is None or window is anchor:
        return None
    for open_panel in window.findChildren(MenuPanel):
        if open_panel.parent_panel is None and open_panel.isVisible():
            open_panel.close()
    panel = MenuPanel(menu, anchor, window, None, side)
    if at is not None:
        panel.move(_inside(window, window.mapFromGlobal(at), panel.size()))
    else:
        panel.move(place(anchor, window, panel.size()))
    panel.show()
    panel.raise_()
    return panel


def show_made_menu(menu: QMenu, anchor: QWidget, at: QPoint | None = None) -> MenuPanel | None:
    """
    Shows `menu` (see `show_menu`), made for this one time, e.g. for a right click: it goes with its panel, or every
    click would leave one more menu behind.
    """
    panel = show_menu(menu, anchor, at)
    if panel is None:
        menu.deleteLater()
    else:
        panel.destroyed.connect(menu.deleteLater)
    return panel


def open_menu(window: QWidget) -> MenuPanel | None:
    """The menu open in `window` (the first one, not its submenus); None for none."""
    for panel in window.findChildren(MenuPanel):
        if panel.parent_panel is None and panel.isVisible():
            return panel
    return None


def attach_menu(button: QAbstractButton, menu: QMenu) -> None:
    """
    A click on `button` opens `menu` under it, in the window, and a second one closes it. A push button gets the mark
    of a button with a menu at its right end.
    """
    button.clicked.connect(lambda _=False: show_menu(menu, button))
    if isinstance(button, QPushButton):
        MenuMark(button)


class MenuMark(QLabel):
    """The mark at the right end of a push button that opens a menu: a small triangle that points down."""

    def __init__(self, button: QPushButton) -> None:
        super().__init__(button)
        self.button = button
        set_role(button, True, "menu")
        set_role(self, "menu_mark")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(ICON, ICON)
        self._draw()
        button.installEventFilter(self)  # pyright: ignore[reportArgumentType]

    def _draw(self) -> None:
        color = current_colors().text_muted if self.button.isEnabled() else current_colors().placeholder
        self.setPixmap(icon("menu-down", color).pixmap(ICON, ICON))
        self.move(self.button.width() - ICON - Space.S, (self.button.height() - ICON) // 2)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() in (QEvent.Type.Resize, QEvent.Type.StyleChange, QEvent.Type.EnabledChange):
            self._draw()
        return False


def _inside(window: QWidget, point: QPoint, size: QSize) -> QPoint:
    """`point` of `window` moved left or up so that something of `size` there stays inside the window."""
    x = point.x() if point.x() + size.width() <= window.width() else point.x() - size.width()
    y = point.y() if point.y() + size.height() <= window.height() else point.y() - size.height()
    return QPoint(max(0, min(x, window.width() - size.width())), max(0, min(y, window.height() - size.height())))


class MenuRow(QFrame):
    """A row of a menu: an action (its icon or check mark, text, line under it, shortcut), or a submenu (▸)."""

    def __init__(self, panel: MenuPanel, action: QAction, lead: bool, rich: bool) -> None:
        super().__init__()
        self.panel = panel
        self.action = action
        self.submenu = action.menu()
        set_role(self, "menu_item")
        set_role(self, "true" if rich else "false", "rich")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(Space.S, Space.S - 2, Space.S, Space.S - 2)
        layout.setSpacing(Space.S)
        text, _, keys = action.text().partition("\t")
        if not keys and not action.shortcut().isEmpty():
            keys = action.shortcut().toString()
        if lead:
            size = RICH_ICON if rich else ICON
            mark = QLabel()
            mark.setFixedSize(size, size)
            name = action.property(ICON_NAME)
            shown = icon(str(name)) if name else action.icon()
            if action.isCheckable():
                shown = icon("check") if action.isChecked() else QIcon()
            if not shown.isNull():
                mark.setPixmap(shown.pixmap(size, size, self._mode()))
            layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop if rich else Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        self.title = QLabel(plain(text))
        set_role(self.title, "menu_title")
        entity = action.property(ENTITY)
        look = "font-weight: 600;" if rich else ""
        if entity and self.enabled:
            look += f" color: {getattr(current_colors(), str(entity))};"
        if look:
            self.title.setStyleSheet(look)
        texts.addWidget(self.title)
        detail = action.property(DETAIL)
        self.detail: QLabel | None = None
        if detail:
            self.detail = QLabel()
            set_role(self.detail, "menu_detail")
            self.detail.setTextFormat(Qt.TextFormat.RichText)
            self.detail.setText(help_text(str(detail)))
            self.detail.setWordWrap(True)
            self.detail.setFixedWidth(RICH_WIDTH)
            texts.addWidget(self.detail)
        layout.addLayout(texts)
        layout.addStretch(1)
        if keys:
            shortcut = QLabel(keys)
            set_role(shortcut, "menu_key")
            layout.addSpacing(Space.L)
            layout.addWidget(shortcut, 0, Qt.AlignmentFlag.AlignTop if rich else Qt.AlignmentFlag.AlignVCenter)
        if self.submenu is not None:
            arrow = QLabel()
            arrow.setPixmap(icon("chevron-right", current_colors().text_muted).pixmap(ICON, ICON, self._mode()))
            layout.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setEnabled(self.enabled)
        if action.toolTip() and action.toolTip() != plain(text) and not detail:
            self.setToolTip(action.toolTip())

    @property
    def enabled(self) -> bool:
        """Whether it can be picked: an enabled action, and a submenu that is enabled and has something in it."""
        if not self.action.isEnabled():
            return False
        return self.submenu is None or (self.submenu.isEnabled() and bool(_shown(self.submenu)))

    def _mode(self) -> QIcon.Mode:
        return QIcon.Mode.Normal if self.enabled else QIcon.Mode.Disabled

    def set_current(self, current: bool) -> None:
        set_role(self, "true" if current else "false", "current")

    def enterEvent(self, event: QEvent | None) -> None:
        super().enterEvent(event)  # type: ignore[arg-type]
        self.panel.hover(self)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        # back onto a row whose submenu the keys closed
        if self.panel.current is not self:
            self.panel.hover(self)
        super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if (
            a0 is not None
            and a0.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(a0.position().toPoint())
        ):
            self.panel.activate(self, keys=False)
            return
        super().mouseReleaseEvent(a0)


class MenuPanel(Popover):
    """
    A menu (or a submenu, with `parent_panel`) as a popover. It closes on a pick, a click outside of it, Esc, or the
    window changing its size; Alt leaves it open. Up and Down pick a row, Enter (or Space) takes it, Right opens a
    submenu and Left closes it, a letter takes the row with that key (the letter after `&`).
    """

    def __init__(
        self,
        menu: QMenu,
        anchor: QWidget,
        window: QWidget,
        parent_panel: MenuPanel | None = None,
        side: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(anchor, window)
        self.menu = menu
        self.parent_panel = parent_panel
        self.side = side
        self.child: MenuPanel | None = None
        self.current: MenuRow | None = None
        self.rows: list[MenuRow] = []
        set_role(self, "popup")
        set_role(self, "menu", "variant")
        lift(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.aboutToShow.emit()
        actions = _shown(menu)
        rich = any(action.property(DETAIL) for action in actions)
        lead = any(not action.icon().isNull() or action.isCheckable() for action in actions)
        content = QWidget()
        set_role(content, "menu_content")
        rows = QVBoxLayout(content)
        rows.setContentsMargins(Space.XS, Space.XS, Space.XS, Space.XS)
        rows.setSpacing(2 if rich else 0)
        for index, action in enumerate(actions):
            if action.isSeparator():
                if action.text():
                    heading = QLabel(plain(action.text()))
                    set_role(heading, "menu_section")
                    if index:
                        rows.addSpacing(Space.XS)
                    rows.addWidget(heading)
                elif 0 < index < len(actions) - 1:
                    line = QFrame()
                    set_role(line, "menu_separator")
                    line.setFixedHeight(1)
                    rows.addSpacing(Space.XS)
                    rows.addWidget(line)
                    rows.addSpacing(Space.XS)
                continue
            row = MenuRow(self, action, lead, rich)
            self.rows.append(row)
            rows.addWidget(row)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        self.scroller: QScrollArea | None = None
        widest = window.width() - 2 * Space.XS
        if content.sizeHint().width() > widest:
            # wider than the window (a long problem): the texts wrap
            for row in self.rows:
                others = 3 * Space.S + (ICON + Space.S if lead else 0) + (ICON + Space.S if row.submenu else 0)
                row.title.setWordWrap(True)
                row.title.setFixedWidth(max(Space.XXL, widest - 2 - 2 * Space.XS - others))
                for nested in row.findChildren(QLayout):
                    nested.invalidate()
            rows.invalidate()
            content.setFixedWidth(widest - 2)
        hint = content.sizeHint()
        room = window.height() - 2 * Space.XS
        if hint.height() > room:
            # taller than the window: it scrolls
            self.scroller = QScrollArea()
            set_role(self.scroller, "menu")
            self.scroller.setFrameShape(QFrame.Shape.NoFrame)
            self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroller.setWidgetResizable(True)
            self.scroller.setWidget(content)
            bar = self.scroller.verticalScrollBar()
            extra = bar.sizeHint().width() if bar is not None else 0
            self.scroller.setFixedSize(hint.width() + extra, room - 2)
            layout.addWidget(self.scroller)
        else:
            layout.addWidget(content)
        layout.activate()
        self.adjustSize()

    @property
    def root(self) -> MenuPanel:
        """The menu this one is a submenu of (itself for the menu)."""
        return self if self.parent_panel is None else self.parent_panel.root

    @property
    def deepest(self) -> MenuPanel:
        """The submenu open the furthest down (itself without one): where the keys go."""
        return self if self.child is None or not self.child.isVisible() else self.child.deepest

    def row(self, text: str) -> MenuRow:
        """The row of the text (without `&` and shortcut), for tests and for those who pick by name."""
        (found,) = [row for row in self.rows if row.title.text() == text]
        return found

    # -- picking ----------------------------------------------------------------------------------------------------

    def set_current(self, row: MenuRow | None) -> None:
        if self.current is row:
            return
        if self.current is not None:
            self.current.set_current(False)
        self.current = row
        if row is not None:
            row.set_current(True)
            if self.scroller is not None:
                self.scroller.ensureWidgetVisible(row, 0, 0)

    def hover(self, row: MenuRow) -> None:
        """The mouse is on `row`: it is the current one, and its submenu opens (another one closes)."""
        if not row.enabled:
            self.set_current(None)
            self.close_child()
            return
        self.set_current(row)
        if row.submenu is not None:
            self.open_child(row, keys=False)
        else:
            self.close_child()

    def activate(self, row: MenuRow, keys: bool) -> None:
        """Takes `row`: opens its submenu (its first row picked when by `keys`), or closes the menu and triggers it."""
        if not row.enabled:
            return
        if row.submenu is not None:
            self.set_current(row)
            self.open_child(row, keys)
            return
        self.root.close()
        row.action.trigger()

    def open_child(self, row: MenuRow, keys: bool) -> None:
        submenu = row.submenu
        assert submenu is not None
        if self.child is not None and self.child.isVisible() and self.child.menu is submenu:
            if keys:
                self.child.step(1)
            return
        self.close_child()
        child = MenuPanel(submenu, row, self.host, self)
        top_left = self.host.mapFromGlobal(row.mapToGlobal(QPoint(0, 0)))
        x = self.x() + self.width() - Space.XS
        if x + child.width() > self.host.width():
            x = self.x() - child.width() + Space.XS
        y = top_left.y() - Space.XS - 1
        child.move(_inside(self.host, QPoint(max(0, x), y), child.size()))
        self.child = child
        child.show()
        child.raise_()
        if keys:
            child.step(1)

    def close_child(self) -> None:
        if self.child is not None:
            if self.child.isVisible():
                self.child.close()
            self.child = None

    def step(self, by: int) -> None:
        """Picks the row `by` rows down (up for less than 0) that can be picked, around the ends."""
        usable = [row for row in self.rows if row.enabled]
        if not usable:
            return
        if self.current not in usable:
            self.set_current(usable[0] if by > 0 else usable[-1])
            return
        assert self.current is not None
        self.set_current(usable[(usable.index(self.current) + by) % len(usable)])

    def key(self, event: QKeyEvent) -> bool:
        """A key for this menu (the deepest one open): True for one it takes."""
        key = Qt.Key(event.key())
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            # the shortcuts of the window, Alt+letter the other menus of the bar
            return False
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self.step(1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Backtab):
            self.step(-1)
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.set_current(None)
            self.step(1 if key == Qt.Key.Key_Home else -1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self.current is not None:
                self.activate(self.current, keys=True)
        elif key == Qt.Key.Key_Escape:
            if self.parent_panel is not None:
                self.parent_panel.close_child()
            else:
                self.close()
        elif key == Qt.Key.Key_Right:
            if self.current is not None and self.current.submenu is not None:
                self.activate(self.current, keys=True)
            elif self.root.side is not None:
                self.root.side(1)
        elif key == Qt.Key.Key_Left:
            if self.parent_panel is not None:
                self.parent_panel.close_child()
            elif self.side is not None:
                self.side(-1)
        elif event.text() and event.text().isprintable():
            letter = event.text().lower()
            matching = [row for row in self.rows if row.enabled and mnemonic(row.action.text()) == letter]
            if matching:
                self.activate(matching[0], keys=True)
        else:
            return key not in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr, Qt.Key.Key_Meta, Qt.Key.Key_Super_L)
        return True

    # -- opening and closing ----------------------------------------------------------------------------------------

    def showEvent(self, event: QShowEvent | None) -> None:
        if self.parent_panel is None:
            # one filter for the menu and its submenus
            super().showEvent(event)
        else:
            QFrame.showEvent(self, event)

    def hideEvent(self, event: QHideEvent | None) -> None:
        self.close_child()
        if self.parent_panel is None:
            super().hideEvent(event)
        else:
            QFrame.hideEvent(self, event)
            if self.parent_panel.child is self:
                self.parent_panel.child = None
        self.menu.aboutToHide.emit()

    def _chain(self) -> list[MenuPanel]:
        panels: list[MenuPanel] = [self]
        while panels[-1].child is not None and panels[-1].child.isVisible():
            panels.append(panels[-1].child)  # type: ignore[arg-type]
        return panels

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if event is None:
            return False
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            where = event.globalPosition().toPoint()
            if any(_on(panel, where) for panel in self._chain()):
                return False
            self.close()
            # a click on the anchor closes it, rather than opening it again
            return _on(self.anchor, where)
        if kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and isinstance(event, QKeyEvent):
            if not self.deepest.key(event) if kind == QEvent.Type.KeyPress else not _takes(event):
                return False
            # before the shortcuts of the window and the field with the focus
            event.accept()
            return True
        if (watched is self.host and kind in (QEvent.Type.Resize, QEvent.Type.Move)) or (
            watched is self.anchor and kind == QEvent.Type.Hide
        ):
            self.close()
        return False


def _takes(event: QKeyEvent) -> bool:
    """Whether a menu takes the key rather than a shortcut of the window: keys without Ctrl or Alt."""
    if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
        return False
    return event.key() not in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr, Qt.Key.Key_Meta)


def _on(widget: QWidget, where: QPoint) -> bool:
    """Whether the point `where` of the screen is on `widget`."""
    return widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(where))


def _shown(menu: QMenu) -> list[QAction]:
    return [action for action in menu.actions() if action.isVisible()]


class MenuBar(QWidget):
    """
    A menu bar whose menus open inside the window (see `show_menu`): a row of their titles, as a `QMenuBar` has them.
    A title opens its menu on a press, Alt and its letter too; with a menu open, the mouse on another title opens that
    one, and Left and Right go to the one before and after.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]
        set_role(self, "menubar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.row = QHBoxLayout(self)
        # as a QMenuBar of the style: its titles a little in from the edge, as high as a line and its padding
        self.row.setContentsMargins(Space.XS + 2, 0, Space.XS + 2, 1)
        self.row.setSpacing(0)
        self.row.addStretch()
        self.titles: list[QToolButton] = []
        self.menus: list[QMenu] = []
        self.panel: MenuPanel | None = None

    def addMenu(self, title: str) -> QMenu:
        """A menu at the end of the bar, its `title` with the letter after `&` for Alt."""
        menu = QMenu(title, self)
        # the shortcuts of its actions are the window's while the bar shows (see `correctActionContext` of Qt)
        self.addAction(menu.menuAction())
        button = QToolButton(self)
        button.setText(title)
        set_role(button, "menubar_item")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(True)
        # as high as a line and its padding: a tool button adds a margin of its own
        button.setFixedHeight(button.fontMetrics().height() + 2 * Space.XS)
        index = len(self.titles)
        button.pressed.connect(lambda index=index: self.toggle(index))
        button.installEventFilter(self)  # pyright: ignore[reportArgumentType]
        menu.aboutToHide.connect(lambda button=button: set_role(button, "false", "open"))
        self.row.insertWidget(index, button)
        self.titles.append(button)
        self.menus.append(menu)
        return menu

    @property
    def opened(self) -> int | None:
        """The index of the menu that is open; None for none."""
        panel = self._panel()
        if panel is None or not panel.isVisible():
            return None
        return self.menus.index(panel.menu)

    def _panel(self) -> MenuPanel | None:
        """The panel of the menu opened last; None once it is closed and deleted (it deletes itself on close)."""
        if self.panel is not None and sip.isdeleted(self.panel):
            self.panel = None
        return self.panel

    def toggle(self, index: int) -> None:
        """Opens the menu `index`, or closes it if it is open."""
        if self.opened == index:
            assert self.panel is not None
            self.panel.close()
            return
        self.open(index)

    def open(self, index: int) -> None:
        panel = self._panel()
        if panel is not None and panel.isVisible():
            panel.close()
        button = self.titles[index]
        panel = show_menu(self.menus[index], button, side=self._side)
        self.panel = panel
        if panel is None:
            return
        set_role(button, "true", "open")

    def _side(self, step: int) -> None:
        opened = self.opened
        if opened is not None:
            self.open((opened + step) % len(self.menus))
            if self.panel is not None:
                self.panel.step(1)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() == QEvent.Type.Enter and a0 in self.titles:
            index = self.titles.index(a0)  # type: ignore[arg-type]
            opened = self.opened
            if opened is not None and opened != index:
                self.open(index)
        return False


class TextMenus(QObject):
    """
    The menus of the right mouse button in the text of `window` (fields, spin boxes, the log, labels whose text can be
    selected) inside the window, rather than as the popup windows Qt opens for them.
    """

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)  # pyright: ignore[reportArgumentType]
        self.window = window
        app_events().watch(self, (QEvent.Type.ContextMenu,))

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None or not isinstance(a1, QContextMenuEvent):
            return False
        if not isinstance(a0, QWidget) or not (a0 is self.window or self.window.isAncestorOf(a0)):
            return False
        menu = text_menu(a0, a1.pos())
        if menu is None:
            return False
        show_made_menu(menu, a0, a1.globalPos())
        return True


def text_menu(widget: QWidget, at: QPoint) -> QMenu | None:
    """The menu of the text of `widget` (Undo, Cut, Copy, Paste, ...) at `at` of it; None for a widget without text."""
    scroll = widget.parentWidget()
    if isinstance(scroll, QPlainTextEdit | QTextEdit) and scroll.viewport() is widget:
        return scroll.createStandardContextMenu(at)
    if isinstance(widget, QAbstractSpinBox):
        edit = widget.findChild(QLineEdit)
        return edit.createStandardContextMenu() if edit is not None else None
    if isinstance(widget, QLineEdit):
        return widget.createStandardContextMenu()
    if isinstance(widget, QLabel) and widget.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse:
        menu = QMenu(widget)
        copy = menu.addAction("&Copy")
        assert copy is not None
        copy.setEnabled(widget.hasSelectedText())
        copy.triggered.connect(lambda _=False: QApplication.clipboard().setText(widget.selectedText()))  # type: ignore[union-attr]
        everything = menu.addAction("Select &all")
        assert everything is not None
        everything.triggered.connect(lambda _=False: widget.setSelection(0, len(widget.text())))
        return menu
    return None
