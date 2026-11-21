"""The menus that open inside their window, without a grab of the keyboard and the mouse."""

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QAction, QContextMenuEvent, QEnterEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot

from tests.support.gui import click, menu_texts, open_menu_of, pick
from xtouch_daemon.gui.qt.fields.menu import (
    DETAIL,
    MenuMark,
    MenuPanel,
    attach_menu,
    describe,
    mnemonic,
    open_menu,
    plain,
    show_menu,
    text_menu,
    with_icon,
)
from xtouch_daemon.gui.qt.theme.tokens import Entity
from xtouch_daemon.gui.qt.window.main_window import MainWindow


def a_window(qtbot: QtBot, height: int = 500) -> tuple[QWidget, QPushButton]:
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(500, height)
    button = QPushButton("Menu")
    QVBoxLayout(window).addWidget(button, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    window.show()
    qtbot.waitExposed(window)
    return window, button


def a_menu(button: QWidget, picked: list[str]) -> QMenu:
    """A menu with what menus have: icons, checks, shortcuts, a section, a separator, a submenu, a disabled entry."""
    menu = QMenu(button)

    def add(parent: QMenu, text: str) -> QAction:
        action = parent.addAction(text)
        assert action is not None
        action.triggered.connect(lambda _=False, text=text: picked.append(plain(text)))
        return action

    menu.addSection("Things")
    with_icon(add(menu, "&Open"), "folder")
    add(menu, "&Save").setShortcut(QKeySequence("Ctrl+S"))
    add(menu, "Gone").setEnabled(False)
    add(menu, "Moved\tCtrl+Right")
    menu.addSeparator()
    check = add(menu, "&Wrap")
    check.setCheckable(True)
    check.setChecked(True)
    more = menu.addMenu("&More")
    assert more is not None
    add(more, "&First")
    add(more, "Se&cond")
    return menu


def test_a_menu_opens_inside_the_window_and_a_click_picks(qtbot: QtBot) -> None:
    window, button = a_window(qtbot)
    picked: list[str] = []
    menu = a_menu(button, picked)
    shown: list[bool] = []
    menu.aboutToShow.connect(lambda: shown.append(True))
    attach_menu(button, menu)
    panel = open_menu_of(qtbot, button)
    assert QApplication.activePopupWidget() is None
    assert panel.window() is window
    assert shown == [True]
    assert menu_texts(panel) == ["Open", "Save", "Gone", "Moved", "Wrap", "More"]
    # under the button
    assert panel.y() > button.y() + button.height() - 1
    # the shortcuts at the right, the section title and the separator between the rows
    assert [label.text() for label in panel.findChildren(QLabel) if label.property("role") == "menu_key"] == [
        QKeySequence("Ctrl+S").toString(),
        "Ctrl+Right",
    ]
    assert [label.text() for label in panel.findChildren(QLabel) if label.property("role") == "menu_section"] == [
        "Things"
    ]
    assert not panel.row("Gone").isEnabled()
    pick(qtbot, panel, "Gone")
    assert picked == []
    assert panel.isVisible()
    pick(qtbot, panel, "Save")
    assert picked == ["Save"]
    assert not panel.isVisible()
    assert open_menu(window) is None


def test_keys_move_through_a_menu_and_its_submenus(qtbot: QtBot) -> None:
    _, button = a_window(qtbot)
    picked: list[str] = []
    menu = a_menu(button, picked)
    attach_menu(button, menu)
    panel = open_menu_of(qtbot, button)
    # Down skips what cannot be picked
    for _ in range(3):
        qtbot.keyClick(button, Qt.Key.Key_Down)
    assert panel.current is panel.row("Moved")
    qtbot.keyClick(button, Qt.Key.Key_Up)
    assert panel.current is panel.row("Save")
    qtbot.keyClick(button, Qt.Key.Key_End)
    assert panel.current is panel.row("More")
    # Right opens the submenu with its first row, Left closes it
    qtbot.keyClick(button, Qt.Key.Key_Right)
    child = panel.child
    assert child is not None
    assert child.isVisible()
    assert child.current is child.row("First")
    # beside the menu
    assert child.x() > panel.x()
    qtbot.keyClick(button, Qt.Key.Key_Left)
    assert not child.isVisible()
    assert panel.isVisible()
    # Esc closes a submenu first, then the menu
    qtbot.keyClick(button, Qt.Key.Key_Return)
    assert panel.child is not None
    qtbot.keyClick(button, Qt.Key.Key_Escape)
    assert panel.child is None
    assert panel.isVisible()
    # Alt leaves it open (a QMenu closes)
    qtbot.keyClick(button, Qt.Key.Key_Alt)
    assert panel.isVisible()
    qtbot.keyClick(button, Qt.Key.Key_Escape)
    assert not panel.isVisible()

    # the letter after & picks, in a submenu too; Enter takes the row picked
    panel = open_menu_of(qtbot, button)
    qtbot.keyClick(button, Qt.Key.Key_M)
    qtbot.keyClick(button, Qt.Key.Key_C)
    assert picked == ["Second"]
    assert not panel.isVisible()
    panel = open_menu_of(qtbot, button)
    qtbot.keyClick(button, Qt.Key.Key_Home)
    qtbot.keyClick(button, Qt.Key.Key_Space)
    assert picked == ["Second", "Open"]
    # a checked entry is unchecked by a pick
    action = menu.actions()[6]
    assert plain(action.text()) == "Wrap"
    panel = open_menu_of(qtbot, button)
    qtbot.keyClick(button, Qt.Key.Key_W)
    assert not action.isChecked()


def test_the_mouse_opens_submenus_and_a_click_outside_closes(qtbot: QtBot) -> None:
    window, button = a_window(qtbot)
    picked: list[str] = []
    attach_menu(button, a_menu(button, picked))
    panel = open_menu_of(qtbot, button)
    panel.hover(panel.row("More"))
    assert panel.current is panel.row("More")
    child = panel.child
    assert child is not None
    pick(qtbot, child, "First")
    assert picked == ["First"]
    assert not panel.isVisible()
    assert not child.isVisible()
    # on another row the submenu closes; on one that cannot be picked nothing is current
    panel = open_menu_of(qtbot, button)
    panel.hover(panel.row("More"))
    panel.hover(panel.row("Open"))
    assert panel.child is None
    panel.hover(panel.row("Gone"))
    assert panel.current is None
    # a click on the button closes it rather than opening it again
    click(qtbot, button)
    assert not panel.isVisible()
    assert open_menu(window) is None
    panel = open_menu_of(qtbot, button)
    qtbot.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(490, 490))
    assert not panel.isVisible()
    assert picked == ["First"]


def test_a_menu_at_a_point_stays_inside_the_window_and_scrolls_when_long(qtbot: QtBot) -> None:
    window, button = a_window(qtbot, height=300)
    menu = QMenu(button)
    for number in range(40):
        menu.addAction(f"Entry {number}")
    panel = show_menu(menu, button, window.mapToGlobal(QPoint(480, 290)))
    assert panel is not None
    assert panel.scroller is not None
    assert panel.geometry().bottom() < window.height()
    assert panel.geometry().right() < window.width()
    panel.step(-1)
    last = panel.row("Entry 39")
    assert panel.current is last
    assert not last.visibleRegion().isEmpty()
    panel.close()
    # nothing opens for a widget without a window around it
    alone = QWidget()
    qtbot.addWidget(alone)
    assert show_menu(menu, alone) is None


def test_rich_entries_say_what_they_do_in_the_color_of_what_they_add(qtbot: QtBot) -> None:
    _, button = a_window(qtbot)
    menu = QMenu(button)
    action = menu.addAction("Output")
    assert action is not None
    describe(with_icon(action, "volume-high"), "The fader sets the volume of `speaker`.", Entity.CHANNEL)
    assert action.property(DETAIL) == "The fader sets the volume of `speaker`."
    attach_menu(button, menu)
    # a push button with a menu shows a mark
    assert button.findChild(MenuMark) is not None
    panel = open_menu_of(qtbot, button)
    row = panel.row("Output")
    assert row.detail is not None
    assert "<code>speaker</code>" in row.detail.text()
    assert row.detail.wordWrap()
    assert "color" in row.title.styleSheet()
    assert row.property("rich") == "true"
    panel.close()


def test_mnemonics_and_texts() -> None:
    assert plain("Save &and apply") == "Save and apply"
    assert plain("Fish && chips") == "Fish & chips"
    assert mnemonic("Save &and apply") == "a"
    assert mnemonic("Fish && chips") == ""


def test_the_menu_bar_opens_its_menus_inside_the_window(qtbot: QtBot, window: MainWindow) -> None:
    bar = window.menu_bar
    # Alt and a letter open a menu, in the window
    qtbot.keyClick(window, Qt.Key.Key_V, Qt.KeyboardModifier.AltModifier)
    panel = open_menu(window)
    assert panel is not None
    assert panel.menu.title() == "&View"
    assert bar.titles[2].property("open") == "true"
    # Alt alone leaves it open
    qtbot.keyClick(window, Qt.Key.Key_Alt)
    assert panel.isVisible()
    # Right goes to the next menu, Left back
    qtbot.keyClick(window, Qt.Key.Key_Right)
    assert bar.opened == 3
    qtbot.keyClick(window, Qt.Key.Key_Left)
    assert bar.opened == 2
    # with a menu open, the mouse on another title opens that one
    corner = QPointF(2, 2)
    QApplication.sendEvent(bar.titles[0], QEnterEvent(corner, corner, corner))
    assert bar.opened == 0
    # a press on its title closes it
    qtbot.mousePress(bar.titles[0], Qt.MouseButton.LeftButton)
    assert bar.opened is None
    assert bar.titles[0].property("open") == "false"
    qtbot.mousePress(bar.titles[1], Qt.MouseButton.LeftButton)
    assert bar.opened == 1
    bar.toggle(1)
    assert bar.opened is None
    # a submenu: View, Zoom
    bar.open(2)
    panel = open_menu(window)
    assert panel is not None
    panel.hover(panel.row("Zoom"))
    assert panel.child is not None
    pick(qtbot, panel.child, "Zoom in")
    assert open_menu(window) is None


def test_the_shortcuts_of_the_menus_work_though_the_menus_never_show(qtbot: QtBot, window: MainWindow) -> None:
    window.activateWindow()
    qtbot.keyClick(window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert window.current_page == "states"
    qtbot.keyClick(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert window.current_page == "channels"
    # also the toggle of a dock that is no action of the window
    shown = window.log_dock.isVisible()
    qtbot.keyClick(window, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert window.log_dock.isVisible() != shown


def test_the_text_of_a_field_has_its_menu_inside_the_window(qtbot: QtBot, window: MainWindow) -> None:
    window.show_page("states")
    edit = window.states_page.id_edit
    edit.setFocus()
    position = QPoint(5, 5)
    QApplication.sendEvent(
        edit, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, edit.mapToGlobal(position))
    )
    panel = open_menu(window)
    assert panel is not None
    assert "Select All" in menu_texts(panel)
    pick(qtbot, panel, "Select All")
    assert edit.selectedText() == edit.text()


def test_a_strip_has_its_menu_where_it_is_clicked(qtbot: QtBot, window: MainWindow) -> None:
    preview = window.device_view.preview
    view = preview.strips[1]
    position = QPoint(10, 40)
    with qtbot.waitSignal(preview.moved) as moved:
        QApplication.sendEvent(
            view, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, view.mapToGlobal(position))
        )
        panel = open_menu(window)
        assert isinstance(panel, MenuPanel)
        assert menu_texts(panel) == ["Move left", "Move right"]
        assert panel.pos() == view.mapTo(window, position)
        pick(qtbot, panel, "Move right")
    assert moved.args == [1, 2]


def test_the_texts_have_their_menus(qtbot: QtBot) -> None:
    log = QPlainTextEdit("a line")
    spin = QSpinBox()
    selectable = QLabel("some text")
    selectable.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    for widget in (log, spin, selectable):
        qtbot.addWidget(widget)
    viewport = log.viewport()
    assert viewport is not None
    assert text_menu(viewport, QPoint(1, 1)) is not None
    assert text_menu(spin, QPoint(1, 1)) is not None
    assert text_menu(QLabel("plain"), QPoint(1, 1)) is None
    menu = text_menu(selectable, QPoint(1, 1))
    assert menu is not None
    copy, everything = menu.actions()
    assert not copy.isEnabled()
    everything.trigger()
    assert selectable.selectedText() == "some text"
    menu = text_menu(selectable, QPoint(1, 1))
    assert menu is not None
    copy = menu.actions()[0]
    assert copy.isEnabled()
    copy.trigger()
    clipboard = QApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "some text"


def test_a_text_wider_than_the_window_wraps(qtbot: QtBot) -> None:
    window, button = a_window(qtbot)
    menu = QMenu(button)
    menu.addAction("A problem that is explained at length, " * 6)
    panel = show_menu(menu, button)
    assert panel is not None
    assert panel.width() <= window.width()
    assert panel.rows[0].title.wordWrap()
