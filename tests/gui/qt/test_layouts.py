"""
Layouts in the window: the bar of the layouts, adding and editing them.
"""

from pathlib import Path

from PyQt6.QtWidgets import QPushButton, QToolButton
from pytestqt.qtbot import QtBot

from tests.support.gui import LAYOUT_CONFIG, FakeLiveDaemon, MakeWindow, buttons, click, row, strip_state, type_into
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.codec import encode_reply, encode_request
from xtouch_daemon.live.messages import Reply, Snapshot, SwitchLayout, fingerprint


def tab_texts(window: MainWindow) -> list[str]:
    return [window.layout_bar.tabs.tabText(index) for index in range(window.layout_bar.tabs.count())]


def test_the_layouts_are_tabs_above_the_preview(qtbot: QtBot, layouts: MainWindow):
    window = layouts
    assert tab_texts(window) == ["default", "gaming", "music"]
    assert window.layout_bar.tabs.currentIndex() == 0
    # without the daemon there is nothing to show it on
    assert not window.layout_bar.show_button.isEnabled()

    window.layout_bar.tabs.setCurrentIndex(1)

    assert window.document.layout_name == "gaming"
    assert window.preview.strips[0].face.look.detail.startswith("like the default layout")
    assert window.preview.strips[1].face.look.kind == "voip"
    assert window.tabs.tabText(0).startswith("Strip 1")
    # the inherit type is offered in a layout, but not in the default one
    assert buttons(window.strip_page, QPushButton, lambda button: button.text() == "Inherit")
    window.layout_bar.tabs.setCurrentIndex(0)
    assert window.document.layout is None
    assert not buttons(window.strip_page, QPushButton, lambda button: button.text() == "Inherit")


def test_the_layout_page_names_the_layout(qtbot: QtBot, layouts: MainWindow):
    window = layouts
    window.show_page("layout")
    assert window.current_page == "layout"
    # the default layout has no options
    assert window.layout_page.rows == []

    window.layout_bar.tabs.setCurrentIndex(2)
    assert window.current_page == "layout"
    assert [option_row.option.name for option_row in window.layout_page.rows] == [
        "name",
        "label",
        "apps",
        "processes",
        "priority",
        "meter_point",
    ]
    type_into(qtbot, row(window, "name", "layout").line, "tunes")
    assert tab_texts(window) == ["default", "gaming", "tunes"]
    assert 'name = "tunes"' in window.document.render()
    type_into(qtbot, row(window, "label", "layout").line, "Tunes")
    assert window.document.get(("layout", "label")) == "Tunes"
    click(qtbot, row(window, "label", "layout").reset)
    assert window.document.get(("layout", "label")) is None
    # a wrong name is a problem of the layout
    type_into(qtbot, row(window, "name", "layout").line, "Tunes!")
    assert window.problems_button.text() == "1 problem"
    window.problems_menu.actions()[0].trigger()
    assert window.current_page == "layout"


def test_layouts_are_added_moved_and_removed(qtbot: QtBot, layouts: MainWindow):
    window = layouts
    window.layout_bar.tabs.setCurrentIndex(1)
    menu = window.layout_bar.add_button.menu()
    assert menu is not None
    empty, copied = menu.actions()

    copied.trigger()
    assert tab_texts(window) == ["default", "gaming", "music", "layout_2"]
    assert window.layout_bar.tabs.currentIndex() == 3
    assert window.current_page == "layout"
    assert [strip.type for strip in window.document.strips] == ["inherit", "voip", "voip"]
    assert "Added the layout layout_2" in window.status.text()
    empty.trigger()
    assert window.document.layout_name == "layout_3"
    assert window.document.strips == []

    left = buttons(window.layout_page, QToolButton, lambda button: "left" in button.toolTip())
    right = buttons(window.layout_page, QToolButton, lambda button: "right" in button.toolTip())
    assert not right[0].isEnabled()
    click(qtbot, left[0])
    assert tab_texts(window) == ["default", "gaming", "music", "layout_3", "layout_2"]
    assert window.layout_bar.tabs.currentIndex() == 3

    (remove,) = buttons(window.layout_page, QPushButton, lambda button: button.text() == "Remove layout")
    click(qtbot, remove)
    assert tab_texts(window) == ["default", "gaming", "music", "layout_2"]
    assert window.document.layout is None
    # one step each
    window.undo()
    assert tab_texts(window) == ["default", "gaming", "music", "layout_3", "layout_2"]


def test_a_problem_of_another_layout_leads_to_it(layouts: MainWindow):
    window = layouts
    window.document.edit_layout(0)
    window.document.set(("strip", 1, "max_volume"), 999)
    window.document.edit_layout(1)
    window.document.set(("layout", "priority"), "high")
    window.document.edit_layout(None)
    window.editor.edited()

    next(action for action in window.problems_menu.actions() if "max_volume" in action.text()).trigger()
    assert (window.document.layout_name, window.selected, window.current_page) == ("gaming", 1, "strip")
    next(action for action in window.problems_menu.actions() if "priority" in action.text()).trigger()
    assert (window.document.layout_name, window.current_page) == ("music", "layout")


def layout_snapshot(window: MainWindow, layout: str | None) -> Snapshot:
    saved = window.document.saved_config
    assert saved is not None
    strips = tuple(strip_state(("Live", "")) for _ in range(8))
    return Snapshot(fingerprint(saved), True, True, None, strips, layout=layout, layouts=("default", "gaming", "music"))


def test_the_device_shows_one_layout_live(
    qtbot: QtBot, make_window: MakeWindow, path: Path, live_daemon: FakeLiveDaemon
):
    path.write_text(LAYOUT_CONFIG)
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(layout_snapshot(window, "gaming"))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)

    assert tab_texts(window) == ["default", "gaming ●", "music"]
    # the default layout is not on the device
    assert not window.preview.strips[0].face.live
    assert window.layout_bar.show_button.isEnabled()
    window.layout_bar.tabs.setCurrentIndex(1)
    assert window.preview.strips[0].face.live
    assert not window.layout_bar.show_button.isEnabled()

    window.layout_bar.tabs.setCurrentIndex(2)
    click(qtbot, window.layout_bar.show_button)
    assert window.status.text() == "Asked the daemon to show the layout music."
    (client,) = live_daemon.clients
    qtbot.waitUntil(lambda: client.bytesAvailable() > 0)
    assert bytes(client.readAll().data()) == encode_request(SwitchLayout("music"))
    # the daemon does not have it (e.g. renamed in the file meanwhile)
    live_daemon.send_line(encode_reply(Reply("layout", False, "There is no layout music (default, gaming)")))
    qtbot.waitUntil(lambda: window.status.text() == "There is no layout music (default, gaming)")
    # a switch that worked is told by the snapshots
    live_daemon.send_line(encode_reply(Reply("layout", True, "music")))

    # a daemon of before layouts shows the default one
    live_daemon.send(layout_snapshot(window, None))
    qtbot.waitUntil(lambda: tab_texts(window)[0] == "default ●")


def test_nothing_is_sent_without_the_daemon(layouts: MainWindow):
    window = layouts
    window.layout_bar.tabs.setCurrentIndex(1)
    window.show_layout_on_device()
    assert window.status.text() == ""
