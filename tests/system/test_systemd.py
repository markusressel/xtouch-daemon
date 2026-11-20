import logging
import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.packaging import install_package
from tests.support.systemd import FakeSystemctl
from xtouch_daemon.system import systemd
from xtouch_daemon.system.systemd import (
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


# -- controlling the service --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("properties", "installed", "running", "enabled", "description"),
    [
        ("LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n", True, True, True, "running"),
        (
            "LoadState=loaded\nActiveState=reloading\nUnitFileState=disabled\n",
            True,
            True,
            False,
            "running, not enabled",
        ),
        ("LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\n", True, False, True, "stopped"),
        ("LoadState=loaded\nActiveState=failed\nUnitFileState=enabled\n", True, False, True, "failed"),
        ("LoadState=loaded\nActiveState=activating\nUnitFileState=enabled\n", True, False, True, "activating"),
        ("LoadState=not-found\nActiveState=inactive\nUnitFileState=\n", False, False, False, "not installed"),
    ],
)
def test_the_state_of_the_service(
    properties: str, installed: bool, running: bool, enabled: bool, description: str
) -> None:
    systemctl = FakeSystemctl(properties)

    state = systemd.Service(systemctl).state()

    assert (state.installed, state.running, state.enabled, state.describe()) == (
        installed,
        running,
        enabled,
        description,
    )
    assert systemctl.commands == [
        [
            "systemctl",
            "--user",
            "show",
            systemd.UNIT_NAME,
            "--property=LoadState,ActiveState,UnitFileState,FragmentPath,ExecStart",
        ]
    ]
    assert (state.unit, state.program, state.packaged) == (None, None, False)


def test_the_state_tells_the_unit_and_its_program() -> None:
    program = "/home/me/xtouch-daemon/.venv/bin/xtouch-daemon"
    systemctl = FakeSystemctl(
        "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
        "FragmentPath=/home/me/.config/systemd/user/xtouch-daemon.service\n"
        f"ExecStart={{ path={program} ; argv[]={program} run ; ignore_errors=no ; start_time=[n/a] ; pid=0 }}\n"
    )

    state = systemd.Service(systemctl).state()

    assert state.unit == Path("/home/me/.config/systemd/user/xtouch-daemon.service")
    assert state.program == program
    assert not state.packaged

    systemctl.properties = (
        f"LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\nFragmentPath={systemd.PACKAGED_UNIT}\n"
    )
    assert systemd.Service(systemctl).state().packaged


def test_installs_starts_restarts_and_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    systemctl = FakeSystemctl()
    service = systemd.Service(systemctl)

    path = service.install("/opt/xtouch-daemon", start=True)
    service.restart()
    service.stop()

    assert path == tmp_path / "systemd" / "user" / systemd.UNIT_NAME
    assert unit_path().read_text() == unit_file("/opt/xtouch-daemon")
    assert systemctl.commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", systemd.UNIT_NAME],
        ["systemctl", "--user", "restart", systemd.UNIT_NAME],
        ["systemctl", "--user", "stop", systemd.UNIT_NAME],
    ]


def test_a_service_that_does_not_wait_only_queues_its_jobs() -> None:
    # the GUI: it goes on drawing (and being) the device while the daemon stops
    systemctl = FakeSystemctl()
    service = systemd.Service(systemctl, wait=False)

    service.start()
    service.restart()
    service.stop()

    assert systemctl.commands == [
        ["systemctl", "--user", "enable", "--now", "--no-block", systemd.UNIT_NAME],
        ["systemctl", "--user", "restart", "--no-block", systemd.UNIT_NAME],
        ["systemctl", "--user", "stop", "--no-block", systemd.UNIT_NAME],
    ]


def test_this_program_is_the_one_of_the_package_when_it_lives_there() -> None:
    assert not systemd.runs_packaged()
    assert not systemd.uses_packaged_unit()

    install_package(contains_this_program=False)
    assert not systemd.uses_packaged_unit()

    install_package()
    assert systemd.runs_packaged()
    assert systemd.uses_packaged_unit()


def test_a_unit_in_the_user_configuration_overrides_the_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    unit_path().parent.mkdir(parents=True)
    unit_path().write_text(unit_file("/opt/xtouch-daemon"))
    # without the package it is the only one
    assert not systemd.overrides_packaged_unit()

    install_package()

    assert systemd.overrides_packaged_unit()
    unit_path().unlink()
    assert not systemd.overrides_packaged_unit()


def test_the_program_of_the_package_takes_its_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    install_package()
    systemctl = FakeSystemctl()

    assert systemd.Service(systemctl).install("/usr/bin/xtouch-daemon", start=True) is None

    assert not unit_path().exists()
    assert systemctl.commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", systemd.UNIT_NAME],
    ]


@pytest.mark.parametrize(
    ("properties", "commands"),
    [
        (
            "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n",
            [
                ["disable", systemd.UNIT_NAME],
                ["daemon-reload"],
                ["enable", systemd.UNIT_NAME],
                ["restart", systemd.UNIT_NAME],
            ],
        ),
        ("LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n", [["daemon-reload"]]),
    ],
)
def test_removing_the_override_keeps_the_service_enabled_and_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, properties: str, commands: list[list[str]]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_package()
    unit_path().parent.mkdir(parents=True)
    unit_path().write_text(unit_file("/opt/xtouch-daemon"))
    systemctl = FakeSystemctl(properties)

    assert systemd.Service(systemctl).remove_override() == unit_path()

    assert not unit_path().exists()
    assert [command[2:] for command in systemctl.commands[1:]] == commands


def test_commands_return_their_output() -> None:
    assert systemd.run_command(["echo", "hello"]) == "hello\n"


def test_a_failing_command_says_why() -> None:
    with pytest.raises(systemd.ServiceError, match=r"^sh -c echo broken >&2; exit 3 failed: broken$"):
        systemd.run_command(["sh", "-c", "echo broken >&2; exit 3"])
    with pytest.raises(systemd.ServiceError, match=r"failed: exit code 4$"):
        systemd.run_command(["sh", "-c", "exit 4"])


def test_a_missing_systemctl_is_reported() -> None:
    with pytest.raises(systemd.ServiceError, match="xtouch-no-such-command is not installed"):
        systemd.run_command(["xtouch-no-such-command"])


def test_the_executable_is_the_installed_command_or_this_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd.shutil, "which", lambda name: "/usr/bin/xtouch-daemon")
    assert systemd.executable() == "/usr/bin/xtouch-daemon"

    monkeypatch.setattr(systemd.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["/opt/venv/bin/xtouch-daemon", "gui"])
    assert systemd.executable() == "/opt/venv/bin/xtouch-daemon"
