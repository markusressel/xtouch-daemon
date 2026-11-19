"""
`run` and `test`.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.cli import CONFIG, STATE, invoke
from tests.support.packaging import install_package
from xtouch_daemon import __version__, cli
from xtouch_daemon.audio.media import MprisPlayers
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.cli import daemon as run_commands
from xtouch_daemon.cli import sound as sound_commands
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.model import Config
from xtouch_daemon.hardware.surface import Surface
from xtouch_daemon.hardware.transport import SocketPort
from xtouch_daemon.system import instance, systemd


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (LookupError("X-Touch-Ext is not connected"), "X-Touch-Ext is not connected: is it switched on, in MC mode"),
        (OSError("busy"), "can't open X-Touch-Ext (busy). Is the daemon running?"),
    ],
)
def test_test_explains_why_the_device_can_not_be_used(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    async def selftest(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(run_commands, "run_selftest", selftest)

    result = CliRunner().invoke(cli.main, ["test"])

    assert result.exit_code == 1
    assert message in result.output


def test_test_runs_the_selftest_and_ends_quietly_on_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    async def selftest(device_name: str, echo: object, show_events: bool, surface: object = None) -> None:
        calls.append((device_name, show_events))
        raise KeyboardInterrupt

    monkeypatch.setattr(run_commands, "run_selftest", selftest)

    assert invoke("test", "--no-events").exit_code == 0
    assert calls == [("X-Touch-Ext", False)]


def test_run_starts_the_daemon_with_the_configuration(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[Config, Path | None]] = []
    sockets: list[Path] = []
    levels: list[int] = []
    surfaces: list[Surface | None] = []

    class FakeDaemon:
        def __init__(
            self,
            config: Config,
            backend: object,
            surface: Surface | None,
            config_path: Path | None,
            live_socket: Path,
            players: object,
            state_dir: Path,
        ) -> None:
            started.append((config, config_path))
            sockets.append(live_socket)
            surfaces.append(surface)
            # what it remembers, in the state directory of the user
            assert state_dir == instance.state_dir()
            assert state_dir.name == "xtouch-daemon"
            # the media players of the session
            assert isinstance(players, MprisPlayers)

        async def run(self) -> None:
            pass

    monkeypatch.setattr(run_commands, "Daemon", FakeDaemon)
    monkeypatch.setattr(systemd, "setup_logging", levels.append)

    assert invoke("run", "-c", str(config_file), "--log-level", "debug").exit_code == 0
    assert started[0][0] == parse_config(CONFIG)
    assert started[0][1] == config_file
    assert sockets == [instance.socket_file()]
    assert levels == [10]
    # the device of the configuration, unless the virtual one is asked for
    assert surfaces == [None]
    assert invoke("run", "-c", str(config_file), "--virtual-device").exit_code == 0
    virtual = surfaces[1]
    assert virtual is not None
    assert isinstance(virtual.port, SocketPort)
    assert virtual.port.path == instance.virtual_device_socket_file()
    assert virtual.device_name == "the virtual X-Touch-Ext"


def test_run_says_that_it_runs_and_a_second_one_does_not_start(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[instance.Instance | None] = []

    class FakeDaemon:
        def __init__(
            self,
            config: Config,
            backend: object,
            surface: Surface | None,
            config_path: Path | None,
            live_socket: Path,
            players: object,
            state_dir: Path,
        ) -> None:
            pass

        async def run(self) -> None:
            seen.append(instance.running())

    monkeypatch.setattr(run_commands, "Daemon", FakeDaemon)
    monkeypatch.setattr(systemd, "setup_logging", lambda level: None)
    monkeypatch.setattr(instance, "_alive", lambda pid: True)

    assert invoke("run", "-c", str(config_file)).exit_code == 0
    assert seen[0] is not None
    assert seen[0].config == config_file.resolve()
    assert instance.running() is None

    instance.runtime_file().write_text('{"pid": 4242, "config": "/other.toml", "systemd": true}')
    result = invoke("run", "-c", str(config_file))
    assert result.exit_code == 1
    assert "xtouch-daemon runs already (process 4242, /other.toml)" in result.output
    assert len(seen) == 1


def test_install_service_writes_the_unit(config_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(systemd.shutil, "which", lambda name: "/opt/bin/xtouch-daemon")
    monkeypatch.setattr(systemd, "run_command", lambda command: commands.append(command) or "")

    result = invoke("install-service")

    assert "ExecStart=/opt/bin/xtouch-daemon run" in systemd.unit_path().read_text()
    assert commands == [["systemctl", "--user", "daemon-reload"]]
    assert "systemctl --user enable --now xtouch-daemon.service" in result.output

    commands.clear()
    result = invoke("install-service", "--now")
    assert commands[-1] == ["systemctl", "--user", "enable", "--now", systemd.UNIT_NAME]
    assert "Start it with" not in result.output


def test_install_service_takes_the_unit_of_the_package(config_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_package()
    commands: list[list[str]] = []
    monkeypatch.setattr(systemd, "run_command", lambda command: commands.append(command) or "")

    result = invoke("install-service")

    assert not systemd.unit_path().exists()
    assert commands == [["systemctl", "--user", "daemon-reload"]]
    assert f"The package installed {systemd.PACKAGED_UNIT}\n" in result.output
    assert "Start it with: systemctl --user enable --now xtouch-daemon.service" in result.output
    assert "overrides" not in result.output

    # one written before, by a checkout
    systemd.unit_path().parent.mkdir(parents=True)
    systemd.unit_path().write_text(systemd.unit_file("/opt/bin/xtouch-daemon"))
    result = invoke("install-service", "--now")
    assert commands[-1] == ["systemctl", "--user", "enable", "--now", systemd.UNIT_NAME]
    assert f"{systemd.unit_path()} overrides it: xtouch-daemon install-service --remove-override" in result.output


def test_install_service_removes_the_override(config_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_package()
    systemd.unit_path().parent.mkdir(parents=True)
    systemd.unit_path().write_text(systemd.unit_file("/opt/bin/xtouch-daemon"))
    commands: list[list[str]] = []
    state = "LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n"
    monkeypatch.setattr(systemd, "run_command", lambda command: commands.append(command) or state)

    result = invoke("install-service", "--remove-override")

    assert not systemd.unit_path().exists()
    assert commands[-1] == ["systemctl", "--user", "daemon-reload"]
    assert result.output == f"Removed {systemd.unit_path()}: the service uses {systemd.PACKAGED_UNIT} now\n"

    # nothing to remove any more
    result = CliRunner().invoke(cli.main, ["install-service", "--remove-override"])
    assert result.exit_code == 1
    assert f"Error: {systemd.unit_path()} does not override {systemd.PACKAGED_UNIT}" in result.output


def test_install_service_reports_a_failing_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(command: list[str]) -> str:
        raise systemd.ServiceError("systemctl is not installed: is this a systemd system?")

    monkeypatch.setattr(systemd, "run_command", fail)

    result = CliRunner().invoke(cli.main, ["install-service"])

    assert result.exit_code == 1
    assert "Error: systemctl is not installed" in result.output


def test_the_package_runs_as_a_module(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["python -m xtouch_daemon", "--version"])

    with pytest.raises(SystemExit) as exit_:
        runpy.run_module("xtouch_daemon", run_name="__main__")

    assert exit_.value.code == 0
    assert capsys.readouterr().out == f"xtouch-daemon, version {__version__}\n"


def test_the_sound_server_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import pulsectl_asyncio

    from xtouch_daemon.audio.pulse import PulseBackend

    clients: list[str] = []

    class FakePulse:
        def __init__(self, name: str) -> None:
            clients.append(name)

        async def __aenter__(self) -> FakePulse:
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

    async def snapshot(pulse: object) -> AudioState:
        assert isinstance(pulse, FakePulse)
        return STATE

    monkeypatch.setattr(pulsectl_asyncio, "PulseAsync", FakePulse)
    monkeypatch.setattr(PulseBackend, "snapshot", staticmethod(snapshot))

    assert sound_commands._audio_state() == STATE
    assert clients == ["xtouch-daemon-cli"]
