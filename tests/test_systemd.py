import logging
import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from xtouch_daemon import systemd
from xtouch_daemon.systemd import (
    JournalFormatter,
    notify,
    reloading,
    setup_logging,
    under_journal,
    unit_file,
    unit_path,
)


@pytest.fixture
def notify_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[socket.socket]:
    path = tmp_path / "notify"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.bind(str(path))
        sock.settimeout(1)
        monkeypatch.setenv("NOTIFY_SOCKET", str(path))
        yield sock


def test_tells_systemd_the_state(notify_socket: socket.socket):
    assert notify("READY=1", "STATUS=Running")
    assert notify_socket.recv(1024) == b"READY=1\nSTATUS=Running"


def test_a_reload_comes_with_the_monotonic_time(notify_socket: socket.socket):
    assert reloading()
    reload, monotonic = notify_socket.recv(1024).decode().split("\n")
    assert reload == "RELOADING=1"
    assert monotonic.startswith("MONOTONIC_USEC=")
    assert int(monotonic.removeprefix("MONOTONIC_USEC=")) > 0


def test_an_abstract_socket_starts_with_an_at(monkeypatch: pytest.MonkeyPatch):
    name = f"xtouch-daemon-test-{os.getpid()}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.bind("\0" + name)
        sock.settimeout(1)
        monkeypatch.setenv("NOTIFY_SOCKET", "@" + name)
        assert notify("READY=1")
        assert sock.recv(1024) == b"READY=1"


def test_without_systemd_nothing_is_told(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert not notify("READY=1")
    # a socket that is gone
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "gone"))
    assert not notify("READY=1")


def stderr_stream() -> str:
    stat = os.fstat(sys.stderr.fileno())
    return f"{stat.st_dev}:{stat.st_ino}"


def test_knows_whether_stderr_goes_to_the_journal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JOURNAL_STREAM", raising=False)
    assert not under_journal()
    monkeypatch.setenv("JOURNAL_STREAM", stderr_stream())
    assert under_journal()
    # stderr was redirected: the stream is inherited, but no longer stderr
    monkeypatch.setenv("JOURNAL_STREAM", "1:1")
    assert not under_journal()
    monkeypatch.setenv("JOURNAL_STREAM", "garbage")
    assert not under_journal()


def test_a_closed_stderr_is_not_the_journal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JOURNAL_STREAM", "1:1")

    def closed(fd: int) -> os.stat_result:
        raise OSError(9, "Bad file descriptor")

    # only around the call: pytest uses os.fstat too
    with monkeypatch.context() as patch:
        patch.setattr(systemd.os, "fstat", closed)
        journal = under_journal()
    assert not journal


def record(level: int, message: str) -> logging.LogRecord:
    return logging.LogRecord("xtouch_daemon.test", level, __file__, 1, message, None, None)


def test_journal_lines_carry_their_priority():
    formatter = JournalFormatter("%(name)s: %(message)s")
    assert formatter.format(record(logging.WARNING, "careful")) == "<4>xtouch_daemon.test: careful"
    assert formatter.format(record(logging.ERROR, "one\ntwo")) == "<3>xtouch_daemon.test: one\n<3>two"
    assert formatter.format(record(logging.CRITICAL, "x")).startswith("<2>")
    assert formatter.format(record(logging.DEBUG, "x")).startswith("<7>")
    # a level of its own is informational
    assert formatter.format(record(25, "x")).startswith("<6>")


@pytest.fixture
def root_logger() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield root
    root.handlers[:] = handlers
    root.setLevel(level)


def test_logs_for_the_journal_or_the_terminal(root_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(systemd, "under_journal", lambda: True)
    setup_logging(logging.DEBUG)
    assert root_logger.level == logging.DEBUG
    [handler] = root_logger.handlers
    assert isinstance(handler.formatter, JournalFormatter)

    monkeypatch.setattr(systemd, "under_journal", lambda: False)
    setup_logging(logging.INFO)
    assert root_logger.level == logging.INFO
    [handler] = root_logger.handlers
    assert handler.formatter is not None
    assert not isinstance(handler.formatter, JournalFormatter)
    assert "INFO" in handler.formatter.format(record(logging.INFO, "hello"))


def test_the_unit_lives_in_the_user_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert unit_path() == tmp_path / "systemd" / "user" / "xtouch-daemon.service"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert unit_path() == tmp_path / ".config" / "systemd" / "user" / "xtouch-daemon.service"


def test_the_unit_runs_the_daemon_as_a_notify_service():
    unit = unit_file("/home/user/.local/bin/xtouch-daemon")
    assert "ExecStart=/home/user/.local/bin/xtouch-daemon run\n" in unit
    assert "Type=notify\n" in unit
    assert "ExecReload=kill -HUP $MAINPID\n" in unit
