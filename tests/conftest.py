"""
What every test gets: guards that keep it from leaving processes behind, touching the machine it runs on or starting
programs, quick faders, and the fakes most tests use (`backend`, `surface`, `env`). The fakes themselves, and helpers
to import, are in `tests.support`.
"""

import asyncio
import gc
import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.support import host
from tests.support.audio import FakeBackend
from tests.support.hardware import RecordingSurface
from tests.support.processes import child_processes
from xtouch_daemon.audio import meter as meter_module
from xtouch_daemon.audio.meter import CaptureTarget
from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.hardware import midi
from xtouch_daemon.hardware import strip as strip_module
from xtouch_daemon.hardware import surface as surface_module
from xtouch_daemon.strips.base import StripEnv
from xtouch_daemon.system import launch as launch_module
from xtouch_daemon.system import processes, systemd

# windows of the GUI tests are never shown on the display of the machine
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def pytest_collection_finish(session: pytest.Session) -> None:
    """
    What the modules and the collection made stays for the whole run: frozen, the `gc.collect()` of `no_leaks` after
    every test looks only at what tests made since, not at the more than 100,000 objects of the imports.
    """
    gc.collect()
    gc.freeze()


@pytest.fixture(autouse=True)
def no_leaks() -> Iterator[None]:
    """
    Fails the test that leaves a process behind, instead of a random later one: the transport of a process that is not
    waited for warns when it is garbage collected (`filterwarnings = ["error"]`), whichever test runs then. Its teardown
    runs after the event loop of the test is closed, which cancels the tasks the test left and waits for them.
    """
    before = child_processes()
    yield
    # the transports of what the test left warn now, in this test
    gc.collect()
    leaked = child_processes() - before
    assert not leaked, f"the test left processes behind: {sorted(leaked)}"


def in_real_time(node: pytest.Item) -> bool:
    """Whether the test runs in real time (`pytest.mark.looptime(False)`), not in the virtual time of looptime."""
    marker = node.get_closest_marker("looptime")
    return marker is not None and bool(marker.args) and not marker.args[0]


async def capture_nothing(
    target: CaptureTarget, feed: Callable[[float], None], playing: Callable[[], bool], command: str
) -> None:
    await asyncio.Event().wait()


@pytest.fixture(autouse=True)
def no_captures_in_virtual_time(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    In virtual time the meters start no process: it would end in real time, and the virtual time of a timeout that
    waits for it (e.g. for the shutdown of the daemon) could be over long before.
    """
    assert isinstance(request.node, pytest.Item)
    if not in_real_time(request.node):
        monkeypatch.setattr(meter_module, "capture", capture_nothing)


@pytest.fixture(autouse=True)
def no_host(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Tests see nothing of the machine they run on: not the user's files, the session bus, systemd, the processes, sound
    cards or MIDI devices. Touching them fails the test (`HostAccessError`), unless it is marked `host`.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path / 'no-session-bus'}")
    for variable in ("NOTIFY_SOCKET", "JOURNAL_STREAM", "INVOCATION_ID"):
        monkeypatch.delenv(variable, raising=False)
    # no processes run
    (tmp_path / "proc").mkdir()
    monkeypatch.setattr(processes, "PROC", tmp_path / "proc")
    monkeypatch.setattr(midi, "PROC_ASOUND_CARDS", tmp_path / "proc" / "asound" / "cards")
    monkeypatch.setattr(midi, "DEV_SND", tmp_path / "dev" / "snd")
    if request.node.get_closest_marker("host") is not None:
        yield
        return
    with host.guarded() as accessed:
        yield
    assert not accessed, f"the test touched the machine it runs on: {accessed}"


@pytest.fixture(autouse=True)
def no_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The release package is not installed, also on a machine that has it: its paths are in the temporary directory."""
    monkeypatch.setattr(systemd, "PACKAGED_UNIT", tmp_path / "package" / "systemd" / "user" / systemd.UNIT_NAME)
    monkeypatch.setattr(systemd, "PACKAGE_ROOT", tmp_path / "package" / "xtouch-daemon")


@pytest.fixture(autouse=True)
def no_launches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing a test does starts a program on the machine it runs on (e.g. a Mumble): use a `FakeLauncher`."""

    def refuse(command: list[str]) -> None:
        raise AssertionError(f"a test would launch {command}")

    monkeypatch.setattr(launch_module, "spawn_detached", refuse)


@pytest.fixture(autouse=True)
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Where `xtouch-daemon run` says that it runs: not the real one, which a daemon on this machine may use. Its state
    directory is not the real one either.
    """
    path = tmp_path / "runtime"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(path))
    # nor what it remembers
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return path


@pytest.fixture(autouse=True)
def quick_faders(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The faders send their targets again at once, their slow moves are as fast as the others, the startup and shutdown
    sequences are not staggered, and a move without a touch is given up on at once: waiting for that adds nothing to
    most tests.
    """
    monkeypatch.setattr(strip_module, "FADER_CONFIRM_DELAYS", (0.0, 0.0))
    monkeypatch.setattr(strip_module, "FADER_SLOW_SMOOTH_TIME", strip_module.FADER_SMOOTH_TIME)
    monkeypatch.setattr(surface_module, "SEQUENCE_STAGGER", 0.0)
    monkeypatch.setattr(surface_module, "SHOW_STAGGER", 0.0)
    monkeypatch.setattr(surface_module, "SHOW_STEP", 0.0)
    monkeypatch.setattr(surface_module, "TOUCH_GRACE", 0.0)


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def socket_dir() -> Iterator[Path]:
    """A directory with a short path: the path of a Unix socket has at most 107 bytes, which tmp_path may exceed."""
    with tempfile.TemporaryDirectory(prefix="xtl-") as path:
        yield Path(path)


@pytest.fixture
def surface() -> RecordingSurface:
    return RecordingSurface()


@pytest.fixture
def env(backend: FakeBackend) -> StripEnv:
    # a fader of 0..100 % over its whole travel: fractions in the tests are volumes
    return StripEnv(backend, BehaviorConfig(max_volume=100))
