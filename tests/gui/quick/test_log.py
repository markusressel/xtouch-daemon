"""
The log of the daemon in the window in Qt Quick: asked for while the panel shows, colored by level, filtered by
level, searched, and following its end.
"""

import dataclasses
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtCore import QMetaObject, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtQuick import QQuickItem

from tests.gui.quick.conftest import MakeUi
from tests.support.gui import FakeLiveDaemon, strip_state
from tests.support.quick import Ui
from xtouch_daemon.gui.domain.tokens import THEMES, ThemeMode
from xtouch_daemon.gui.quick.engine import theme_of
from xtouch_daemon.gui.quick.window import log as log_module
from xtouch_daemon.live.messages import FEATURES, EndLog, LogEntry, LogLines, Snapshot, WatchLog, fingerprint


@pytest.fixture
def live_daemon() -> Iterator[FakeLiveDaemon]:
    # a short path: the one of a Unix socket has at most 107 bytes, which tmp_path may exceed
    with tempfile.TemporaryDirectory(prefix="xtl-") as directory:
        fake = FakeLiveDaemon(Path(directory) / "live.sock")
        yield fake
        fake.close()


def snapshot(ui: Ui, **changes: object) -> Snapshot:
    config = ui.app.editor.document.saved_config
    assert config is not None
    strips = tuple(strip_state() for _ in range(8))
    state = Snapshot(fingerprint(config), True, True, None, strips, features=FEATURES)
    return dataclasses.replace(state, **changes)  # pyright: ignore[reportArgumentType]


def live_ui(make_ui: MakeUi, live_daemon: FakeLiveDaemon, **changes: object) -> Ui:
    ui = make_ui(live_socket=live_daemon.path)
    ui.wait_until(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(ui, **changes))
    ui.wait_until(lambda: ui.app.shell.live.snapshot is not None)
    return ui


def entry(seq: int, level: str = "INFO", message: str = "") -> LogEntry:
    when = datetime(2026, 11, 19, 12, 30, 0).timestamp() + seq
    return LogEntry(seq, when, level, "xtouch_daemon.daemon.lifecycle", message or f"record {seq}")


def log(ui: Ui) -> log_module.LogBackend:
    return ui.app.shell._log  # pyright: ignore[reportPrivateUsage]


def open_log(ui: Ui, live_daemon: FakeLiveDaemon, *entries: LogEntry) -> None:
    """Opens the panel Log from the menu View; the daemon answers with `entries`."""
    ui.app.shell.trigger("log")
    ui.wait_until(lambda: WatchLog() in live_daemon.requests)
    live_daemon.send_log(LogLines(entries, backlog=True))
    ui.wait_until(lambda: len(log(ui).history.entries) == len(entries))
    ui.settle()


def text(ui: Ui) -> str:
    return log(ui).text()


def color_at(ui: Ui, position: int) -> str:
    document = log(ui).document
    assert document is not None
    block = document.findBlock(position)
    fragment = block.begin().fragment()
    # the format of the last fragment of the line
    while not fragment.isValid() or not fragment.contains(position):
        fragment = block.begin().fragment() if not fragment.isValid() else fragment
        break
    iterator = block.begin()
    last = None
    while not iterator.atEnd():
        last = iterator.fragment()
        iterator += 1
    assert last is not None
    return last.charFormat().foreground().color().name()


def search(ui: Ui, word: str) -> None:
    """Types `word` into the search field, in place of what was there."""
    field = ui.item("log_search")
    ui.focus(field)
    QMetaObject.invokeMethod(field, "selectAll")
    if word:
        ui.type(word)
    else:
        ui.key(Qt.Key.Key_Backspace)


def flick(ui: Ui) -> QQuickItem:
    parent = ui.item("log_text").parentItem()
    assert parent is not None
    flickable = parent.parentItem()
    assert flickable is not None
    return flickable


def test_the_log_is_asked_for_while_the_panel_shows(make_ui: MakeUi, live_daemon: FakeLiveDaemon):
    ui = live_ui(make_ui, live_daemon)
    # hidden at first: nothing is asked for
    assert not ui.shows("logPanel")
    assert WatchLog() not in live_daemon.requests

    open_log(ui, live_daemon, entry(1, message="Running with 2 channels"), entry(2, "WARNING", "Lost it"))

    assert ui.shows("logPanel")
    first, second = (f"{datetime.fromtimestamp(entry(seq).time):%H:%M:%S}" for seq in (1, 2))
    assert text(ui) == (
        f"{first} INFO    xtouch_daemon.daemon.lifecycle: Running with 2 channels\n"
        f"{second} WARNING xtouch_daemon.daemon.lifecycle: Lost it"
    )
    # colored by its level
    assert color_at(ui, len(text(ui)) - 1) == THEMES[ThemeMode.DARK].warning
    assert ui.text("log_message") == ""

    # new records come in
    live_daemon.send_log(LogLines((entry(3, "ERROR", "Broken\nTraceback ..."),)))
    ui.wait_until(lambda: "Traceback ..." in text(ui))

    ui.app.shell.trigger("log")
    ui.wait_until(lambda: EndLog() in live_daemon.requests)
    assert not ui.shows("logPanel")


def test_the_level_picked_filters_the_records(make_ui: MakeUi, live_daemon: FakeLiveDaemon):
    ui = live_ui(make_ui, live_daemon)
    open_log(ui, live_daemon, entry(1, "DEBUG", "noise"), entry(2, "INFO", "news"), entry(3, "CRITICAL"))
    assert "noise" in text(ui)

    log(ui).setLevelIndex(log(ui).levels.index("Warning"))

    assert "noise" not in text(ui)
    assert "news" not in text(ui)
    assert "record 3" in text(ui)
    # and the new ones
    live_daemon.send_log(LogLines((entry(4, "INFO", "later"), entry(5, "ERROR", "worse"))))
    ui.wait_until(lambda: "worse" in text(ui))
    assert "later" not in text(ui)
    # another theme draws them again, in its colors
    theme_of(ui.engine).setMode(ThemeMode.LIGHT.value)
    assert color_at(ui, len(text(ui)) - 1) == THEMES[ThemeMode.LIGHT].error


def test_the_level_is_picked_in_the_panel(make_ui: MakeUi, live_daemon: FakeLiveDaemon):
    ui = live_ui(make_ui, live_daemon)
    open_log(ui, live_daemon, entry(1, "DEBUG", "noise"), entry(2, "ERROR", "bad"))

    combo = ui.item("log_level")
    ui.focus(combo)
    for _ in range(3):
        ui.key(Qt.Key.Key_Down)
    assert log(ui).levelIndex == 3
    assert "noise" not in text(ui)


def test_the_search_marks_its_matches_and_goes_from_one_to_the_next(make_ui: MakeUi, live_daemon: FakeLiveDaemon):
    ui = live_ui(make_ui, live_daemon)
    open_log(ui, live_daemon, entry(1, message="Mic muted"), entry(2, message="mic unmuted"), entry(3))
    view = log(ui)

    search(ui, "MIC")

    assert len(view.marks) == 2
    assert ui.text("log_matches") == "2 matches"
    # the match has the background of the accent in the text
    start = view.marks[0][0]
    document = view.document
    assert document is not None
    cursor = QTextCursor(document)
    cursor.setPosition(start + 1)
    assert cursor.charFormat().background().color().alpha() == log_module.MARK_ALPHA
    # new records are searched too
    live_daemon.send_log(LogLines((entry(4, message="mic again"),)))
    ui.wait_until(lambda: ui.text("log_matches") == "3 matches")

    area = ui.item("log_text")
    ui.key(Qt.Key.Key_Return)
    assert str(area.property("selectedText")).lower() == "mic"
    first = area.property("selectionStart")
    # going to a match stops following the end
    assert not view.follow
    ui.key(Qt.Key.Key_Return)
    assert area.property("selectionStart") > first
    ui.key(Qt.Key.Key_Return)
    # after the last one: from the top
    ui.key(Qt.Key.Key_Return)
    assert area.property("selectionStart") == first

    search(ui, "nowhere")
    assert ui.text("log_matches") == "No match"
    ui.key(Qt.Key.Key_Return)
    search(ui, "record 3")
    assert ui.text("log_matches") == "1 match"
    search(ui, "")
    assert ui.text("log_matches") == ""
    assert view.marks == []


def test_many_matches_are_counted_but_not_all_marked(
    make_ui: MakeUi, live_daemon: FakeLiveDaemon, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(log_module, "MAX_MATCHES", 2)
    ui = live_ui(make_ui, live_daemon)
    open_log(ui, live_daemon, *(entry(seq) for seq in range(1, 5)))

    search(ui, "record")

    assert ui.text("log_matches") == "4 matches"
    assert len(log(ui).marks) == 2


def test_the_end_stays_in_view_until_scrolled_away(make_ui: MakeUi, live_daemon: FakeLiveDaemon):
    ui = live_ui(make_ui, live_daemon)
    open_log(ui, live_daemon, *(entry(seq) for seq in range(1, 300)))
    area = flick(ui)

    def at_end() -> bool:
        return area.property("contentY") >= area.property("contentHeight") - area.height() - 1

    ui.wait_until(at_end)
    assert log(ui).follow
    assert area.property("contentHeight") > area.height()

    # scrolled up by hand: it stays there
    area.setProperty("contentY", 0)
    ui.settle()
    assert not log(ui).follow
    live_daemon.send_log(LogLines((entry(300),)))
    ui.wait_until(lambda: "record 300" in text(ui))
    ui.settle()
    assert area.property("contentY") == 0
    # nor does it go to the end when another level draws the records again
    log(ui).setLevelIndex(1)
    ui.settle()
    assert not log(ui).follow
    assert not at_end()

    # Follow goes to the end, and stays there
    ui.click("log_follow")
    ui.wait_until(at_end)
    assert log(ui).follow
    live_daemon.send_log(LogLines((entry(301),)))
    ui.wait_until(lambda: "record 301" in text(ui))
    ui.wait_until(at_end)
    # back at the end by hand: it follows again
    ui.click("log_follow")
    assert not log(ui).follow
    area.setProperty("contentY", 0)
    area.setProperty("contentY", area.property("contentHeight") - area.height())
    ui.settle()
    assert log(ui).follow


def test_without_a_daemon_the_panel_says_so(make_ui: MakeUi, tmp_path: Path):
    ui = make_ui(live_socket=tmp_path / "nowhere.sock", find_daemon=lambda: None)
    ui.app.shell.trigger("log")
    ui.settle()

    assert ui.shows("log_message")
    assert ui.text("log_message").startswith("No daemon runs")


def test_a_daemon_that_is_too_old_is_named(make_ui: MakeUi, live_daemon: FakeLiveDaemon):
    ui = live_ui(make_ui, live_daemon, features=("preview",))
    ui.app.shell.trigger("log")
    ui.settle()

    assert "too old" in ui.text("log_message")
    assert ui.shows("log_message")
    assert WatchLog() not in live_daemon.requests


def test_the_last_records_stay_when_the_daemon_goes_away_and_it_is_watched_again_when_back(
    make_ui: MakeUi, live_daemon: FakeLiveDaemon
):
    ui = live_ui(make_ui, live_daemon)
    open_log(ui, live_daemon, entry(1, "ERROR", "Last words"))

    for client in live_daemon.clients:
        client.disconnectFromServer()
    live_daemon.clients = []
    ui.wait_until(lambda: ui.app.shell.live.snapshot is None)

    assert "Last words" in text(ui)
    assert "last records of the daemon" in ui.text("log_message")

    # it is back: the window asks again
    live_daemon.requests.clear()
    ui.app.shell.live.connect_to_daemon()
    ui.wait_until(lambda: bool(live_daemon.clients))
    live_daemon.send(snapshot(ui))
    ui.wait_until(lambda: WatchLog() in live_daemon.requests)
    live_daemon.send_log(LogLines((entry(1, message="Started again"),), backlog=True))
    ui.wait_until(lambda: "Started again" in text(ui))
    assert "Last words" not in text(ui)
    ui.settle()
    assert ui.text("log_message") == ""


def test_the_text_keeps_the_latest_records(monkeypatch: pytest.MonkeyPatch, ui: Ui):
    monkeypatch.setattr(log_module, "KEPT", 4)
    monkeypatch.setattr(log_module, "TRIM_STEP", 2)
    view = log(ui)
    view.setSearch("record")
    for seq in range(1, 11):
        view._append(entry(seq))  # pyright: ignore[reportPrivateUsage]

    # more than 6: back to the latest 4, at the 7th and the 10th
    lines = text(ui).split("\n")
    assert [line.rsplit(": ", 1)[-1] for line in lines] == ["record 7", "record 8", "record 9", "record 10"]
    document = view.document
    assert document is not None
    assert document.blockCount() == 4
    # where each record starts, for the search
    whole = text(ui)
    assert [whole[start : start + len(record)] for start, record in view.placed] == [
        record for _, record in view.placed
    ]
    assert len(view.placed) == 4
    assert view.match_count == 4
    assert [whole[start : start + length] for start, length in view.marks] == ["record"] * 4


def test_the_panel_log_can_be_a_narrow_band(ui: Ui):
    ui.app.shell.trigger("log")
    ui.settle()
    dock = ui.item("logPanel")
    # the bar and a line, not the few lines a scroll area asks for by default
    least = dock.property("SplitView.minimumHeight") if False else ui.item("logPanel").property("leastHeight")
    assert 0 < least < 3 * 32 + 16
