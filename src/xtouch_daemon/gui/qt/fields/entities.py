"""
Fields for the entities of Home Assistant: the entities the window knows (`EntitySource`, read in a thread with the
settings of `[homeassistant]` in the editor), a list of suggestions under a text field that narrows down while typing
(`SuggestionList`, drawn inside the window: no popup that grabs the keyboard), and the line that says why a field has
no suggestions, with a button to the settings (`EntityHint`).
"""

import asyncio
import threading
import time
from collections.abc import Callable

from PyQt6.QtCore import QEvent, QModelIndex, QObject, QPointF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QPainter, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.gui.domain import sources
from xtouch_daemon.gui.domain.entities import (
    EntityCache,
    Fetch,
    Tried,
    domain_icon,
    entity_suggestions,
    section_config,
    try_home_assistant,
    why_no_entities,
)
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.qt.fields.basics import help_label, set_help
from xtouch_daemon.gui.qt.fields.depth import lift
from xtouch_daemon.gui.qt.fields.names import QUERY_ROLE, SUGGESTION_ROLE, SuggestionDelegate
from xtouch_daemon.gui.qt.fields.popover import Popover, _under, place  # pyright: ignore[reportPrivateUsage]
from xtouch_daemon.gui.qt.theme.icons import icon
from xtouch_daemon.gui.qt.theme.style import set_role
from xtouch_daemon.gui.qt.theme.tokens import Space
from xtouch_daemon.homeassistant.client import fetch
from xtouch_daemon.homeassistant.states import EntityState
from xtouch_daemon.live.messages import HomeAssistantState, Snapshot

ROWS = 8
"""The most lines the list shows at once; it scrolls for more."""
LIST_WIDTH = 400
"""The least width of the list: the names of entities are long."""
ICON_SIZE = 16
ICON_ROLE = Qt.ItemDataRole.UserRole + 3
"""The name of the icon of a line, None for none."""


class EntitySource(QObject):
    """
    The entities of Home Assistant the window knows, for the fields of entities: read with the settings of
    `[homeassistant]` in the editor (`settings`, also unsaved ones) when a field wants them (`want()`), in a thread,
    and again with other settings or a minute later. The test of the settings (`test()`) reads them too. `changed`
    tells that they (or why there are none) changed, `tested` the result of a test, `settings_wanted` that a field
    asks for the page of the settings.
    """

    changed = pyqtSignal(arguments=[])
    tested = pyqtSignal(object, arguments=["status"])
    settings_wanted = pyqtSignal(arguments=[])
    _read = pyqtSignal(object, object, bool, arguments=["config", "tried", "test"])

    def __init__(
        self,
        settings: Callable[[], object],
        read: Fetch = fetch,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__()
        self._settings = settings
        self._fetch = read
        self._clock = clock
        self.cache = EntityCache()
        self.live: HomeAssistantState | None = None
        """The daemon's connection to Home Assistant, from its live view."""
        self._read.connect(self._done)

    def config(self) -> HomeAssistantConfig | str | None:
        """The settings in the editor (see `section_config`)."""
        return section_config(self._settings())

    def want(self, again: bool = False) -> None:
        """A field shows: reads the entities if the settings changed or they are old (`again`: in any case)."""
        config = self.config()
        if isinstance(config, HomeAssistantConfig) and self.cache.wants(config, self._clock(), again):
            self._start(config, test=False)
            self.changed.emit()

    def test(self, config: HomeAssistantConfig) -> None:
        """Tries the settings: `tested` has the result; the entities it found are the suggestions then."""
        self._start(config, test=True)

    def _start(self, config: HomeAssistantConfig, test: bool) -> None:
        if not test:
            self.cache.start(config)
        threading.Thread(target=self._run, args=(config, test), name="home assistant", daemon=True).start()

    def _run(self, config: HomeAssistantConfig, test: bool) -> None:
        self._read.emit(config, asyncio.run(try_home_assistant(config, self._fetch)), test)

    def _done(self, config: HomeAssistantConfig, tried: Tried, test: bool) -> None:
        self.cache.done(config, tried, self._clock())
        if test:
            self.tested.emit(tried.status)
        self.changed.emit()

    def show_live(self, snapshot: Snapshot | None) -> None:
        live = snapshot.homeassistant if snapshot is not None else None
        if live != self.live:
            self.live = live
            self.changed.emit()

    @property
    def current(self) -> bool:
        """Whether the entities are of the settings in the editor."""
        config = self.config()
        return isinstance(config, HomeAssistantConfig) and self.cache.config == config

    def suggestions(self) -> tuple[Suggestion, ...]:
        return entity_suggestions(self.cache.entities) if self.current else ()

    def entity(self, entity_id: object) -> EntityState | None:
        return self.cache.entity(entity_id) if self.current else None

    def why(self) -> str:
        """Why there are no suggestions, "" while there are (see `why_no_entities`)."""
        return why_no_entities(self.config(), self.cache, self.live)


def source_of(widget: QWidget) -> EntitySource | None:
    """The entities of the window of `widget` (its `entity_source`), None outside of one."""
    source = getattr(widget.window(), "entity_source", None)
    return source if isinstance(source, EntitySource) else None


class IconDelegate(SuggestionDelegate):
    """A line of a `SuggestionList`: the icon of its domain (`ICON_ROLE`) on the left, then as `SuggestionDelegate`."""

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        name = index.data(ICON_ROLE)
        if not name:
            super().paint(painter, option, index)
            return
        assert painter is not None
        indent = ICON_SIZE + Space.S
        rect = option.rect
        moved = QStyleOptionViewItem(option)
        moved.rect = rect.adjusted(indent, 0, 0, 0)
        # the background of the whole line, the text beside the icon
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else None
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, widget)
        document = self._document(index, moved.rect.width())
        painter.save()
        painter.translate(QPointF(moved.rect.topLeft()))
        document.drawContents(painter)
        painter.restore()
        top = rect.top() + Space.XS + 2
        icon(str(name)).paint(painter, rect.left() + Space.XS, top, ICON_SIZE, ICON_SIZE)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width() + ICON_SIZE + Space.S, size.height()) if index.data(ICON_ROLE) else size


class _ListPopover(Popover):
    """The popover of a `SuggestionList`: a click into its field leaves it open (the caret moves, typing goes on)."""

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonPress
            and _under(self.anchor, event.globalPosition().toPoint())
        ):
            return False
        return super().eventFilter(watched, event)


class SuggestionList(QObject):
    """
    Suggestions under a text field, inside the window: the list opens when the field gets the focus or a click, and
    narrows down while typing (by any part of a value or its detail, or a pattern with `*` and `?`). Up and Down move
    in it, Enter picks, Esc closes it; the focus stays in the field. `picked` has the value picked. `suggest` is asked
    each time; `nothing` says why there are none. `icons` gives the icon of a line, None for none.
    """

    picked = pyqtSignal(str, arguments=["value"])

    def __init__(
        self,
        edit: QLineEdit,
        suggest: Callable[[], tuple[Suggestion, ...]],
        nothing: Callable[[], str],
        icons: Callable[[Suggestion], str | None] | None = None,
    ) -> None:
        # no parent: who makes it keeps it (the stubs of PyQt6 take no parent here)
        super().__init__()
        self.edit = edit
        self.suggest = suggest
        self.nothing = nothing
        self.icons = icons
        self.wanted: Callable[[], None] = lambda: None
        """Called before the list opens: e.g. to read the entities (they come with `refresh()`)."""
        self.items = QStandardItemModel(self)
        self.typed = False
        """Whether the list is for what was typed, rather than all of them."""
        self.popover: _ListPopover | None = None
        self.view: QListView | None = None
        edit.textEdited.connect(lambda _text: self.open(typed=True))
        edit.installEventFilter(self)  # pyright: ignore[reportArgumentType]

    @property
    def is_open(self) -> bool:
        return self.popover is not None and not self.popover.isHidden()

    def fill(self, text: str) -> tuple[Suggestion, ...]:
        """The list for what is typed: the suggestions it has (a line that says why for none)."""
        found = sources.filtered(text, self.suggest())
        self.items.clear()
        for suggestion in found:
            item = QStandardItem(suggestion.value)
            item.setData(suggestion, SUGGESTION_ROLE)
            item.setData(text, QUERY_ROLE)
            item.setData(self.icons(suggestion) if self.icons is not None else None, ICON_ROLE)
            item.setToolTip(suggestion.tip or suggestion.detail or suggestion.value)
            item.setEditable(False)
            self.items.appendRow(item)
        if not found:
            why = self.nothing().replace("`", "")
            item = QStandardItem(f"Nothing known matches {text!r}" if text and not why else why or "None known")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.items.appendRow(item)
        return found

    def open(self, typed: bool = False) -> None:
        """
        Shows the list under the field: for what is `typed`, else all of them, the value of the field picked (to pick
        another one).
        """
        window = self.edit.window()
        if window is None or window is self.edit or not self.edit.isVisible():
            return
        self.typed = typed
        self.wanted()
        self.fill(self.edit.text() if typed else "")
        if not self.is_open:
            self._build(window)
        self._fit()

    def refresh(self) -> None:
        """The suggestions changed: the open list shows them."""
        if self.is_open:
            self.fill(self.edit.text() if self.typed else "")
            self._fit()

    def close(self) -> None:
        if self.popover is not None:
            self.popover.close()
        self.popover = self.view = None

    def _build(self, window: QWidget) -> None:
        popover = _ListPopover(self.edit, window)
        set_role(popover, "popup")
        lift(popover)
        popover.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(popover)
        layout.setContentsMargins(Space.XS, Space.XS, Space.XS, Space.XS)
        view = QListView(popover)
        set_role(view, "choice")
        # the focus stays in the field: typing goes on while the list is open
        view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view.setMouseTracking(True)
        view.entered.connect(
            lambda index: view.setCurrentIndex(index) if index.flags() & Qt.ItemFlag.ItemIsEnabled else None
        )
        view.setFixedWidth(self._width())
        view.setModel(self.items)
        # kept here: the view does not own its delegate
        self.delegate = IconDelegate(view)
        view.setItemDelegate(self.delegate)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.clicked.connect(self._pick)
        layout.addWidget(view)
        popover.destroyed.connect(lambda _=None, popover=popover: self._closed(popover))
        self.popover, self.view = popover, view
        popover.show()
        popover.raise_()

    def _width(self) -> int:
        return max(self.edit.width(), LIST_WIDTH) - 2 * Space.XS

    @staticmethod
    def _hover(view: QListView, index: QModelIndex) -> None:
        if index.flags() & Qt.ItemFlag.ItemIsEnabled:
            view.setCurrentIndex(index)

    def _fit(self) -> None:
        popover, view = self.popover, self.view
        if popover is None or view is None:
            return
        window = popover.host
        view.setFixedWidth(self._width())
        # the lines wrap at that width: their heights anew
        view.reset()
        rows = min(self.items.rowCount(), ROWS)
        height = sum(view.sizeHintForRow(row) for row in range(rows)) + 2 * view.frameWidth()
        view.setFixedHeight(max(height, 1))
        popover.adjustSize()
        popover.move(place(self.edit, window, popover.size()))
        if self.typed:
            # Enter picks the first match
            current = self.items.index(0, 0) if self.edit.text() else QModelIndex()
        else:
            found = self.items.findItems(self.edit.text())
            current = found[0].index() if found and self.edit.text() else QModelIndex()
        if current.isValid() and current.flags() & Qt.ItemFlag.ItemIsEnabled:
            view.setCurrentIndex(current)
            view.scrollTo(current)
        else:
            view.setCurrentIndex(QModelIndex())

    def _closed(self, popover: QFrame) -> None:
        if self.popover is popover:
            self.popover = self.view = None

    def _pick(self, index: QModelIndex) -> None:
        if not index.isValid() or not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        value = str(index.data())
        self.close()
        self.edit.setText(value)
        self.picked.emit(value)

    def _move(self, by: int) -> None:
        view = self.view
        if view is None:
            return
        rows = self.items.rowCount()
        current = view.currentIndex().row()
        row = min(max(0, (current + by) if current >= 0 else 0), rows - 1)
        index = self.items.index(row, 0)
        if index.flags() & Qt.ItemFlag.ItemIsEnabled:
            view.setCurrentIndex(index)
            view.scrollTo(index)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if watched is not self.edit or event is None:
            return False
        kind = event.type()
        if kind in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress) and not self.is_open:
            self.open()
        elif kind == QEvent.Type.FocusOut:
            self.close()
        elif kind == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                if not self.is_open:
                    self.open()
                else:
                    self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.is_open and self.view is not None:
                index = self.view.currentIndex()
                if index.isValid():
                    self._pick(index)
                    return True
                self.close()
            elif key == Qt.Key.Key_Tab:
                self.close()
        return False


class EntityHint(QFrame):
    """
    One muted line under a field of an entity: why it has no suggestions (see `why_no_entities`), and a button to the
    settings of Home Assistant. Hidden while there are suggestions.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Space.S)
        self.text = help_label("", "help")
        layout.addWidget(self.text, 1)
        self.settings = QPushButton("Settings")
        set_role(self.settings, "flat", "variant")
        self.settings.setToolTip("The settings of Home Assistant API: its address and the token")
        self.settings.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings.clicked.connect(self._open_settings)
        layout.addWidget(self.settings, 0, Qt.AlignmentFlag.AlignTop)
        self.source: EntitySource | None = None
        self.hide()

    def show_source(self, source: EntitySource | None) -> None:
        """Says why `source` has no suggestions; none outside of a window."""
        self.source = source
        self.refresh()

    def refresh(self) -> None:
        why = self.source.why() if self.source is not None else ""
        set_help(self.text, why)
        self.setVisible(bool(why))

    def _open_settings(self) -> None:
        if self.source is not None:
            self.source.settings_wanted.emit()


def entity_icon(suggestion: Suggestion) -> str:
    return domain_icon(suggestion.value)


def attach_entity_list(edit: QLineEdit, owner: QWidget, hint: EntityHint | None = None) -> SuggestionList:
    """
    Suggests the entities of the window of `owner` under `edit`, with their icons; `hint` says why there are none.
    The entities are read when the list opens.
    """

    def source() -> EntitySource | None:
        return source_of(owner)

    def nothing() -> str:
        found = source()
        return found.why() if found is not None else ""

    suggestions = SuggestionList(
        edit, lambda: found.suggestions() if (found := source()) is not None else (), nothing, entity_icon
    )
    connected: list[EntitySource] = []

    def wanted() -> None:
        found = source()
        if found is None:
            return
        if found not in connected:
            connected.append(found)
            found.changed.connect(suggestions.refresh)
            if hint is not None:
                found.changed.connect(hint.refresh)
        found.want()
        if hint is not None:
            hint.show_source(found)

    suggestions.wanted = wanted
    return suggestions
