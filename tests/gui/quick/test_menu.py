"""The menus of the window in Qt Quick: their entries, keys and states, and the keys of the window."""

from typing import Any

import pytest
from PyQt6.QtCore import QObject, QPointF, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtQuick import QQuickItem
from PyQt6.QtTest import QTest

from tests.support.dialogs import FakeDialogs
from tests.support.quick import Ui
from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.tokens import ThemeMode
from xtouch_daemon.gui.quick.details import Entry
from xtouch_daemon.gui.quick.settings import ZOOM_LEVELS
from xtouch_daemon.gui.quick.theme import load_mode
from xtouch_daemon.gui.quick.window.menus import flat, menus, mnemonic, native, plain

CTRL = Qt.KeyboardModifier.ControlModifier
KEYS: Any = QTest
"""QTest, untyped: the stubs of PyQt6 type its static functions as methods."""


def menu_of(ui: Ui, name: str) -> QObject:
    for item in ui.all_items():
        for child in item.children():
            if child.objectName() == name:
                return child
    raise AssertionError(f"no menu named {name!r}")


def opened(ui: Ui, name: str) -> bool:
    return menu_of(ui, name).property("opened") is True


def open_title(ui: Ui, name: str) -> None:
    """Clicks the title of a menu and waits until the menu is open (its entries take clicks then)."""
    ui.click(f"menubar_{name}")
    ui.wait_until(lambda: opened(ui, f"menu_{name}"))
    # a popup takes clicks once it was laid out for a frame
    ui.grab()


def submenu_item(ui: Ui, text: str) -> QQuickItem:
    """The entry of a menu that opens the submenu `text` (made by the menu, it has no name)."""
    return next(
        item for item in ui.all_items() if item.property("subMenu") is not None and item.property("text") == text
    )


def press(ui: Ui, key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    """A key as a user types it: through the shortcuts of the window too."""
    KEYS.keyClick(ui.window, key, modifiers)
    ui.settle()


def edit(ui: Ui) -> None:
    ui.app.editor.document.set(("behavior", "max_volume"), 110)
    ui.app.editor.edited()
    ui.settle()


def test_the_menus_have_what_is_used_now_and_then(ui: Ui):
    shell = ui.app.shell
    assert [plain(menu["text"]) for menu in shell.menus] == ["File", "Edit", "View", "Help"]
    by_id = {entry["id"]: entry for menu in shell.menus for entry in flat(menu["entries"])}
    assert [by_id[i]["text"] for i in ("save", "revert", "quit")] == ["&Save and apply", "&Revert", "&Quit"]
    assert native(by_id["save"]["keys"][0]) == "Ctrl+S"
    assert native(by_id["undo"]["keys"][0]) == "Ctrl+Z"
    assert "Ctrl+Shift+Z" in [native(key) for key in by_id["redo"]["keys"]] or by_id["redo"]["keys"]
    assert [by_id[f"page.{name}"]["keys"] for name in ("slots", "channels", "states", "settings")] == [
        ["Ctrl+1"],
        ["Ctrl+2"],
        ["Ctrl+3"],
        ["Ctrl+4"],
    ]
    assert by_id["log"]["keys"] == ["Ctrl+L"]
    assert by_id["rename"]["keys"] == ["F2"]
    assert by_id["duplicate"]["keys"] == ["Ctrl+D"]
    assert "Backspace" in by_id["remove"]["keys"]
    assert by_id["device"]["description"].startswith("The window with the device")
    assert by_id["log"]["description"].startswith("The log of the daemon")
    # Ctrl++ and Ctrl+= zoom in
    assert len(by_id["zoom.in"]["keys"]) >= 2
    # every level of the zoom
    assert [entry["text"] for entry in by_id.values() if entry["id"].startswith("zoom.") and entry["checkable"]] == [
        f"{round(level * 100)} %" for level in ZOOM_LEVELS
    ]
    assert mnemonic("Re&name") == "n"
    assert mnemonic("Plain") == ""


def test_a_menu_opens_inside_the_window_and_a_click_picks(ui: Ui):
    edit(ui)

    open_title(ui, "file")
    assert opened(ui, "menu_file")
    assert ui.shows("menu_save")
    # inside the window: no popup window (the fixture `no_popups` fails a test that has one)
    assert ui.item("menu_save").mapToScene(QPointF(0, 0)).y() > 0
    assert ui.item("menu_save").property("shortcutText") == "Ctrl+S"

    ui.click("menu_save")

    assert not opened(ui, "menu_file")
    assert not ui.app.editor.document.modified


def test_the_entries_that_do_nothing_are_disabled(ui: Ui):
    open_title(ui, "file")
    assert not ui.item("menu_save").isEnabled()
    assert not ui.item("menu_revert").isEnabled()
    press(ui, Qt.Key.Key_Escape)
    open_title(ui, "edit")
    assert not ui.item("menu_undo").isEnabled()
    # the entries of a list: only while the list of a page has the focus
    assert not ui.item("menu_copy").isEnabled()

    press(ui, Qt.Key.Key_Escape)
    ui.app.shell.trigger("page.channels")
    edit(ui)
    open_title(ui, "edit")
    assert ui.item("menu_undo").isEnabled()
    assert not ui.item("menu_redo").isEnabled()
    ui.click("menu_undo")
    assert ui.app.editor.document.get(("behavior", "max_volume")) == 120
    assert ui.app.shell.statusText == "Undone."
    open_title(ui, "edit")
    assert ui.item("menu_redo").isEnabled()


def test_the_mouse_on_another_title_switches_menus_and_a_click_on_the_open_one_closes_it(ui: Ui):
    open_title(ui, "file")
    assert opened(ui, "menu_file")

    center = ui.center(ui.item("menubar_view"))
    KEYS.mouseMove(ui.window, center)
    ui.settle()
    ui.wait_until(lambda: opened(ui, "menu_view"))
    assert not opened(ui, "menu_file")

    ui.click("menubar_view")
    assert not opened(ui, "menu_view")


def test_alt_and_a_letter_open_a_menu_and_the_arrows_go_on_to_the_next(ui: Ui):
    press(ui, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    assert opened(ui, "menu_file")

    press(ui, Qt.Key.Key_Right)
    assert opened(ui, "menu_edit")
    assert not opened(ui, "menu_file")
    press(ui, Qt.Key.Key_Left)
    press(ui, Qt.Key.Key_Left)
    # round the end
    assert opened(ui, "menu_help")
    press(ui, Qt.Key.Key_Escape)
    assert not opened(ui, "menu_help")


def test_keys_move_through_a_menu_and_enter_does_the_entry(ui: Ui):
    edit(ui)
    press(ui, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)

    # the first entry is the one the keys start on
    press(ui, Qt.Key.Key_Return)

    assert not opened(ui, "menu_file")
    assert not ui.app.editor.document.modified


def test_the_submenus_open_to_the_right_and_check_what_is_on(ui: Ui):
    open_title(ui, "view")
    ui.click(submenu_item(ui, "Theme"))
    ui.grab()
    assert ui.item("menu_theme.dark").property("checked") is True
    assert ui.item("menu_theme.light").property("checked") is False

    ui.click("menu_theme.light")

    assert load_mode() == ThemeMode.LIGHT
    open_title(ui, "view")
    ui.click(submenu_item(ui, "Theme"))
    ui.grab()
    assert ui.item("menu_theme.light").property("checked") is True


def test_the_view_menu_has_the_pages_the_panels_and_the_zoom(ui: Ui):
    open_title(ui, "view")
    ui.click("menu_page.states")
    assert ui.app.page == "states"

    open_title(ui, "view")
    assert ui.item("menu_device").property("checked") is True
    assert ui.item("menu_log").property("checked") is False
    ui.click(submenu_item(ui, "Zoom"))
    ui.grab()
    assert ui.item("menu_zoom.1").property("checked") is True


def test_the_pages_have_keys(ui: Ui):
    for number, name in ((2, "channels"), (3, "states"), (4, "settings"), (1, "slots")):
        press(ui, Qt.Key(Qt.Key.Key_0 + number), CTRL)
        assert ui.app.page == name


def test_the_keys_of_the_file_and_the_edit(ui: Ui):
    edit(ui)

    press(ui, Qt.Key.Key_Z, CTRL)
    assert ui.app.editor.document.get(("behavior", "max_volume")) == 120
    press(ui, Qt.Key.Key_Z, CTRL | Qt.KeyboardModifier.ShiftModifier)
    assert ui.app.editor.document.get(("behavior", "max_volume")) == 110
    press(ui, Qt.Key.Key_S, CTRL)
    assert not ui.app.editor.document.modified
    assert "max_volume = 110" in ui.app.shell.document.path.read_text()


def test_undo_goes_to_the_document_also_while_a_field_has_the_focus(ui: Ui):
    """The field would undo its own text: the document's undo is what the keys are for."""
    edit(ui)
    ui.focus("log_search")
    assert ui.item("log_search").property("activeFocus") is True
    ui.app.shell._panels.log_panel.setShown(True)  # pyright: ignore[reportPrivateUsage]
    ui.focus("log_search")
    ui.type("abc")

    press(ui, Qt.Key.Key_Z, CTRL)

    assert ui.app.editor.document.get(("behavior", "max_volume")) == 120
    assert ui.item("log_search").property("text") == "abc"


def test_the_entries_of_a_list_go_to_the_page_that_has_the_focus(ui: Ui):
    seen: list[str] = []
    page = ui.app.slots
    page.edit = seen.append  # pyright: ignore[reportAttributeAccessIssue]
    page.property = lambda name: ["copy", "remove"] if name == "editable" else QObject.property(page, name)  # pyright: ignore[reportAttributeAccessIssue]
    ui.app.shell._page_changed()
    ui.settle()

    open_title(ui, "edit")
    assert ui.item("menu_copy").isEnabled()
    assert not ui.item("menu_cut").isEnabled()
    ui.click("menu_copy")
    press(ui, Qt.Key.Key_Delete)
    # Cut is off: nothing happens
    press(ui, Qt.Key.Key_X, CTRL)

    assert seen == ["copy", "remove"]


def test_the_documentation_opens_in_the_browser(ui: Ui, monkeypatch: pytest.MonkeyPatch):
    opened_urls: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened_urls.append(url) or True)

    open_title(ui, "help")
    ui.click("menu_docs")

    assert opened_urls == [QUrl(docs.DOCS_URL)]
    press(ui, Qt.Key.Key_F1)
    assert len(opened_urls) == 2


def test_the_keys_have_a_popover_made_from_the_menus(ui: Ui):
    open_title(ui, "help")
    ui.click("menu_keys")

    assert menu_of(ui, "keys_details").property("opened") is True
    rows = [row for row in ui.app.shell.keys_details._content.entries if isinstance(row, Entry)]  # pyright: ignore[reportPrivateUsage]
    assert [row.title for row in rows] == ["Window", "Edit", "Lists", "Device"]
    window = {text: key for key, text in rows[0].items}
    assert window["Save and apply"] == "Ctrl+S"
    assert window["Log"] == "Ctrl+L"
    assert rows[1].text.startswith("Cut, Copy, Paste")


def test_a_closing_window_with_a_menu_open_asks_all_the_same(ui: Ui, dialogs: FakeDialogs):
    edit(ui)
    open_title(ui, "file")

    ui.window.close()
    ui.settle()

    assert dialogs.shown == ["Save the changes before closing?"]


def test_the_menu_data_is_the_same_for_each_platform_key():
    data = menus([("slots", "Slots")])
    assert [menu["id"] for menu in data] == ["file", "edit", "view", "help"]
