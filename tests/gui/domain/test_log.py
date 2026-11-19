from datetime import datetime

from xtouch_daemon.gui.domain.log import LogHistory, line, matches, severity, shown
from xtouch_daemon.live.messages import LogEntry, LogLines


def entry(seq: int, level: str = "INFO", message: str = "anything") -> LogEntry:
    return LogEntry(seq, datetime(2026, 11, 19, 12, 30, 1).timestamp(), level, "xtouch_daemon.mqtt", message)


def test_a_record_reads_as_in_the_terminal():
    assert line(entry(1, "WARNING", "Lost the broker")) == "12:30:01 WARNING xtouch_daemon.mqtt: Lost the broker"
    assert line(entry(1, "INFO", "Up")) == "12:30:01 INFO    xtouch_daemon.mqtt: Up"


def test_the_level_picked_shows_its_records_and_those_above():
    assert shown(entry(1, "ERROR"), "WARNING")
    assert shown(entry(1, "WARNING"), "WARNING")
    assert not shown(entry(1, "INFO"), "WARNING")
    assert shown(entry(1, "CRITICAL"), "ERROR")
    # a level of its own counts as INFO
    assert severity("NOTICE") == severity("INFO")
    assert shown(entry(1, "NOTICE"), "INFO")
    assert not shown(entry(1, "NOTICE"), "WARNING")


def test_a_search_ignores_case_and_finds_every_match():
    assert matches("Mic muted, MIC unmuted", "mic") == [(0, 3), (11, 3)]
    assert matches("aaaa", "aa") == [(0, 2), (2, 2)]
    assert matches("anything", "") == []
    assert matches("anything", "else") == []


def test_the_history_keeps_the_latest_records_and_starts_over_with_a_backlog():
    history = LogHistory(size=3)
    history.take(LogLines((entry(1), entry(2, "DEBUG")), backlog=True))
    history.take(LogLines((entry(3), entry(4, "ERROR"))))
    assert [record.seq for record in history.entries] == [2, 3, 4]
    assert [record.seq for record in history.shown("INFO")] == [3, 4]

    # the daemon restarted, or the window watches again
    history.take(LogLines((entry(1),), backlog=True))
    assert [record.seq for record in history.entries] == [1]
