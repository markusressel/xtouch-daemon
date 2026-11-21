"""
The window Log: the log of the running daemon, asked for while the window shows, colored by level, filtered by level,
searched, and following its end.
"""

import dataclasses
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.support.gui import FakeLiveDaemon, MakeWindow, click, strip_state, type_into
from xtouch_daemon.gui.qt import log_view as log_view_module
from xtouch_daemon.gui.qt.theme.tokens import THEMES, ThemeMode
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.live.messages import FEATURES, EndLog, LogEntry, LogLines, Snapshot, WatchLog, fingerprint


@pytest.fixture
def live_daemon(qapp: QApplication) -> Iterator[FakeLiveDaemon]:
    # a short path: the one of a Unix socket has at most 107 bytes, which tmp_path may exceed
    with tempfile.TemporaryDirectory(prefix="xtl-") as directory:
        fake = FakeLiveDaemon(Path(directory) / "live.sock")
        yield fake
        fake.close()


def snapshot(window: MainWindow, **changes: object) -> Snapshot:
    config = window.document.saved_config
    assert config is not None
    strips = tuple(strip_state() for _ in range(8))
    state = Snapshot(fingerprint(config), True, True, None, strips, features=FEATURES)
    return dataclasses.replace(state, **changes)  # pyright: ignore[reportArgumentType]


def live_window(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, **changes: object) -> MainWindow:
    window = make_window(live_socket=live_daemon.path)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(window, **changes))
    qtbot.waitUntil(lambda: window.live.snapshot is not None)
    return window


def entry(seq: int, level: str = "INFO", message: str = "") -> LogEntry:
    when = datetime(2026, 11, 19, 12, 30, 0).timestamp() + seq
    return LogEntry(seq, when, level, "xtouch_daemon.daemon.lifecycle", message or f"record {seq}")


def open_log(qtbot: QtBot, window: MainWindow, live_daemon: FakeLiveDaemon, *entries: LogEntry) -> None:
    """Opens the window Log from the menu View; the daemon answers with `entries`."""
    action = window.log_dock.toggleViewAction()
    assert action is not None
    action.trigger()
    qtbot.waitUntil(lambda: WatchLog() in live_daemon.requests)
    live_daemon.send_log(LogLines(entries, backlog=True))
    qtbot.waitUntil(lambda: len(window.log_view.history.entries) == len(entries))


def text(window: MainWindow) -> str:
    return window.log_view.text.toPlainText()


def test_the_log_is_asked_for_while_the_window_shows(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = live_window(qtbot, make_window, live_daemon)
    # hidden at first: nothing is asked for
    assert window.log_dock.isHidden()
    assert WatchLog() not in live_daemon.requests

    open_log(qtbot, window, live_daemon, entry(1, message="Running with 2 channels"), entry(2, "WARNING", "Lost it"))

    first, second = (f"{datetime.fromtimestamp(entry(seq).time):%H:%M:%S}" for seq in (1, 2))
    assert text(window) == (
        f"{first} INFO    xtouch_daemon.daemon.lifecycle: Running with 2 channels\n"
        f"{second} WARNING xtouch_daemon.daemon.lifecycle: Lost it"
    )
    # colored by its level
    cursor = window.log_view.text.textCursor()
    cursor.setPosition(len(text(window)) - 1)
    assert cursor.charFormat().foreground().color().name() == THEMES[ThemeMode.DARK].warning
    assert window.log_view.message.isHidden()

    # new records come in
    live_daemon.send_log(LogLines((entry(3, "ERROR", "Broken\nTraceback ..."),)))
    qtbot.waitUntil(lambda: "Traceback ..." in text(window))

    window.log_dock.toggleViewAction().trigger()  # pyright: ignore[reportOptionalMemberAccess]
    qtbot.waitUntil(lambda: EndLog() in live_daemon.requests)


def test_the_level_picked_filters_the_records(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon):
    window = live_window(qtbot, make_window, live_daemon)
    open_log(qtbot, window, live_daemon, entry(1, "DEBUG", "noise"), entry(2, "INFO", "news"), entry(3, "CRITICAL"))
    view = window.log_view
    assert "noise" in text(window)

    view.level.setCurrentIndex(view.level.findData("WARNING"))

    assert "noise" not in text(window)
    assert "news" not in text(window)
    assert "record 3" in text(window)
    # and the new ones
    live_daemon.send_log(LogLines((entry(4, "INFO", "later"), entry(5, "ERROR", "worse"))))
    qtbot.waitUntil(lambda: "worse" in text(window))
    assert "later" not in text(window)
    # another theme draws them again, in its colors
    window.set_theme(ThemeMode.LIGHT)
    cursor = window.log_view.text.textCursor()
    cursor.setPosition(len(text(window)) - 1)
    assert cursor.charFormat().foreground().color().name() == THEMES[ThemeMode.LIGHT].error


def test_the_search_marks_its_matches_and_goes_from_one_to_the_next(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = live_window(qtbot, make_window, live_daemon)
    open_log(qtbot, window, live_daemon, entry(1, message="Mic muted"), entry(2, message="mic unmuted"), entry(3))
    view = window.log_view

    type_into(qtbot, view.search, "MIC")

    assert len(view.text.extraSelections()) == 2
    assert view.matches_label.text() == "2 matches"
    # new records are searched too
    live_daemon.send_log(LogLines((entry(4, message="mic again"),)))
    qtbot.waitUntil(lambda: view.matches_label.text() == "3 matches")

    qtbot.keyClick(view.search, Qt.Key.Key_Return)
    assert view.text.textCursor().selectedText().lower() == "mic"
    first = view.text.textCursor().selectionStart()
    # going to a match stops following the end
    assert not view.follow.isChecked()
    qtbot.keyClick(view.search, Qt.Key.Key_Return)
    assert view.text.textCursor().selectionStart() > first
    qtbot.keyClick(view.search, Qt.Key.Key_Return)
    # after the last one: from the top
    qtbot.keyClick(view.search, Qt.Key.Key_Return)
    assert view.text.textCursor().selectionStart() == first

    type_into(qtbot, view.search, "nowhere")
    assert view.matches_label.text() == "No match"
    qtbot.keyClick(view.search, Qt.Key.Key_Return)
    type_into(qtbot, view.search, "record 3")
    assert view.matches_label.text() == "1 match"
    view.search.clear()
    assert view.matches_label.text() == ""
    assert view.text.extraSelections() == []


def test_many_matches_are_counted_but_not_all_marked(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(log_view_module, "MAX_MATCHES", 2)
    window = live_window(qtbot, make_window, live_daemon)
    open_log(qtbot, window, live_daemon, *(entry(seq) for seq in range(1, 5)))

    type_into(qtbot, window.log_view.search, "record")

    assert window.log_view.matches_label.text() == "4 matches"
    assert len(window.log_view.text.extraSelections()) == 2


def test_the_end_stays_in_view_until_scrolled_away(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon):
    window = live_window(qtbot, make_window, live_daemon)
    open_log(qtbot, window, live_daemon, *(entry(seq) for seq in range(1, 300)))
    view = window.log_view
    scroll = view.text.verticalScrollBar()
    assert scroll is not None
    assert view.follow.isChecked()
    assert scroll.value() == scroll.maximum() > 0

    # scrolled up by hand: it stays there
    scroll.setValue(0)
    assert not view.follow.isChecked()
    live_daemon.send_log(LogLines((entry(300),)))
    qtbot.waitUntil(lambda: "record 300" in text(window))
    assert scroll.value() == 0
    # nor does it go to the end when another level draws the records again
    view.level.setCurrentIndex(view.level.findData("INFO"))
    assert not view.follow.isChecked()
    assert scroll.value() < scroll.maximum()

    # Follow goes to the end, and stays there
    click(qtbot, view.follow)
    assert scroll.value() == scroll.maximum()
    live_daemon.send_log(LogLines((entry(301),)))
    qtbot.waitUntil(lambda: "record 301" in text(window))
    assert scroll.value() == scroll.maximum()
    # back at the end by hand: it follows again
    view.follow.setChecked(False)
    scroll.setValue(scroll.maximum() - 1)
    scroll.setValue(scroll.maximum())
    assert view.follow.isChecked()


def test_without_a_daemon_the_window_says_so(qtbot: QtBot, make_window: MakeWindow, tmp_path: Path):
    window = make_window(live_socket=tmp_path / "nowhere.sock")
    window.log_dock.toggleViewAction().trigger()  # pyright: ignore[reportOptionalMemberAccess]

    assert not window.log_view.message.isHidden()
    assert window.log_view.message.text().startswith("No daemon runs")


def test_a_daemon_that_is_too_old_is_named(qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon):
    window = live_window(qtbot, make_window, live_daemon, features=("preview",))
    window.log_dock.toggleViewAction().trigger()  # pyright: ignore[reportOptionalMemberAccess]

    assert "too old" in window.log_view.message.text()
    assert not window.log_view.message.isHidden()
    assert WatchLog() not in live_daemon.requests


def test_the_last_records_stay_when_the_daemon_goes_away_and_it_is_watched_again_when_back(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon
):
    window = live_window(qtbot, make_window, live_daemon)
    open_log(qtbot, window, live_daemon, entry(1, "ERROR", "Last words"))

    for client in live_daemon.clients:
        client.disconnectFromServer()
    live_daemon.clients = []
    qtbot.waitUntil(lambda: window.live.snapshot is None)

    assert "Last words" in text(window)
    assert "last records of the daemon" in window.log_view.message.text()

    # it is back: the window asks again
    live_daemon.requests.clear()
    window.live.connect_to_daemon()
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(window))
    qtbot.waitUntil(lambda: WatchLog() in live_daemon.requests)
    live_daemon.send_log(LogLines((entry(1, message="Started again"),), backlog=True))
    qtbot.waitUntil(lambda: "Started again" in text(window))
    assert "Last words" not in text(window)
    assert window.log_view.message.isHidden()


def test_the_text_keeps_the_latest_records(monkeypatch: pytest.MonkeyPatch, window: MainWindow):
    monkeypatch.setattr(log_view_module, "KEPT", 4)
    monkeypatch.setattr(log_view_module, "TRIM_STEP", 2)
    view = window.log_view
    view.search.setText("record")
    for seq in range(1, 11):
        view._append(entry(seq))  # pyright: ignore[reportPrivateUsage]

    # more than 6: back to the latest 4, at the 7th and the 10th
    lines = view.text.toPlainText().split("\n")
    assert [text.rsplit(": ", 1)[-1] for text in lines] == ["record 7", "record 8", "record 9", "record 10"]
    document = view.text.document()
    assert document is not None
    assert document.blockCount() == 4
    # where each record starts, for the search
    text = view.text.toPlainText()
    assert [text[start : start + len(record)] for start, record in view.placed] == [record for _, record in view.placed]
    assert len(view.placed) == 4
    assert view.match_count == 4
    assert [mark.cursor.selectedText() for mark in view.marks] == ["record"] * 4
