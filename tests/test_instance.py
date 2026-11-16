import json
import os
import signal
from pathlib import Path

import pytest

from xtouch_daemon.system import instance
from xtouch_daemon.system.instance import AlreadyRunning, Instance, registered, running, runtime_file


@pytest.fixture
def alive(monkeypatch: pytest.MonkeyPatch) -> set[int]:
    """The daemons that run: this test runs under pytest, whose command line is not one of a daemon."""
    pids = {os.getpid()}
    monkeypatch.setattr(instance, "_alive", lambda pid: pid in pids)
    return pids


def write(pid: int, config: str = "/home/me/config.toml") -> None:
    runtime_file().parent.mkdir(parents=True, exist_ok=True)
    runtime_file().write_text(json.dumps({"pid": pid, "config": config, "systemd": False}))


def test_the_file_is_in_the_runtime_directory(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    assert runtime_file() == runtime_dir / "xtouch-daemon.json"
    assert instance.socket_file() == runtime_dir / "xtouch-daemon.sock"

    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert runtime_file().parent.name == f"xtouch-daemon-{os.getuid()}"


def test_the_state_is_in_the_state_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert instance.layout_file() == tmp_path / "xtouch-daemon" / "layout"
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert instance.layout_file() == tmp_path / ".local" / "state" / "xtouch-daemon" / "layout"


def test_a_daemon_says_that_it_runs_while_it_runs(alive: set[int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert running() is None

    with registered(tmp_path / "config.toml") as this:
        assert this == Instance(os.getpid(), (tmp_path / "config.toml").resolve(), systemd=False)
        assert running() == this

    assert running() is None
    assert not runtime_file().exists()


def test_systemd_started_the_service(alive: set[int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INVOCATION_ID", "0123")

    with registered(tmp_path / "config.toml"):
        found = running()
        assert found is not None
        assert found.systemd


def test_a_second_daemon_does_not_start(alive: set[int], tmp_path: Path):
    alive.add(4242)
    write(4242)

    with (
        pytest.raises(AlreadyRunning, match=r"runs already \(process 4242, /home/me/config.toml\)"),
        registered(tmp_path / "config.toml"),
    ):
        pytest.fail("it ran")

    # the file stays the one of the other daemon
    assert json.loads(runtime_file().read_text())["pid"] == 4242


def test_the_file_of_a_daemon_that_was_killed_is_replaced(alive: set[int], tmp_path: Path):
    write(4242)
    assert running() is None

    with registered(tmp_path / "config.toml") as this:
        assert running() == this


def test_a_file_another_daemon_took_over_is_left_alone(alive: set[int], tmp_path: Path):
    with registered(tmp_path / "config.toml"):
        alive.add(4242)
        write(4242)
    assert json.loads(runtime_file().read_text())["pid"] == 4242

    # or removed
    alive.remove(4242)
    with registered(tmp_path / "config.toml"):
        runtime_file().unlink()


def test_a_process_is_a_daemon_by_its_command_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    command_lines = {1: b"/usr/bin/python\0/opt/bin/xtouch-daemon\0run\0", 2: b"/usr/bin/xtouch-daemon\0gui\0"}
    real = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path.parts[1] != "proc":
            return real(path)
        pid = int(path.parts[2])
        if pid not in command_lines:
            raise FileNotFoundError(path)
        return command_lines[pid]

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert instance._alive(1)
    assert not instance._alive(2)
    assert not instance._alive(3)


def test_a_reload_is_a_hangup(monkeypatch: pytest.MonkeyPatch):
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, signum: signals.append((pid, signum)))

    Instance(4242, Path("/config.toml"), systemd=False).reload()

    assert signals == [(4242, signal.SIGHUP)]
