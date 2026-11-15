import sys
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from tests.conftest import output, source, stream
from xtouch_daemon import __version__, cli, systemd
from xtouch_daemon.audio import pulse
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config import Config, parse_config

CONFIG = """
[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
label = "Out"

[[strip]]
type = "input"
device = "mic"
select = false
meter = false

[[strip]]
type = "apps"
label = "Browser"
match = ["brave", "firefox"]
color = "yellow"

[[strip]]
type = "empty"
"""

STATE = AudioState(
    outputs=(output("speaker", 50, running=True), output("buds", 30, muted=True)),
    inputs=(source("mic", 80),),
    streams=(
        stream(1, "Brave"),
        stream(2, "WEBRTC VoiceEngine", "Discord", volume=60, corked=True),
        stream(3, "speech-dispatcher-espeak", ""),
    ),
    default_output="speaker",
    default_input="mic",
)


@pytest.fixture(autouse=True)
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "xtouch-daemon" / "config.toml"


@pytest.fixture
def config_file(config_home: Path) -> Path:
    config_home.parent.mkdir(parents=True)
    config_home.write_text(CONFIG)
    return config_home


@pytest.fixture
def audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_audio_state", lambda: STATE)


def invoke(*args: str) -> Result:
    return CliRunner().invoke(cli.main, list(args), catch_exceptions=False)


def test_the_version_is_shown() -> None:
    assert invoke("--version").output.strip().endswith(__version__)


def test_without_a_command_the_help_is_shown() -> None:
    result = invoke()
    assert "Use a Behringer X-Touch Extender as a hardware mixer for PipeWire." in result.output


# -- configuration ------------------------------------------------------------------------------------------------


def test_check_config_shows_what_each_strip_does(config_file: Path) -> None:
    result = invoke("check-config")

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        f"{config_file}: valid",
        "  1. 'Out' the default output (white)",
        "  2. input mic (white, no meter)",
        "  3. 'Browser' applications brave, firefox (yellow)",
        "  4. empty",
        *[f"  {number}. the next application that plays (white)" for number in range(5, 9)],
    ]


def test_check_config_without_a_file_checks_the_defaults() -> None:
    result = invoke("check-config")

    assert result.exit_code == 0
    assert result.output.startswith("No configuration file, the defaults: valid\n")
    assert "select makes it the default" not in result.output


def test_a_named_device_with_select_says_so(tmp_path: Path) -> None:
    path = tmp_path / "other.toml"
    path.write_text('[[strip]]\ntype = "output"\ndevice = "buds"\n')

    assert "1. output buds, select makes it the default (white)" in invoke("check-config", "-c", str(path)).output


def test_check_config_reports_errors(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[behavior]\nmax_volume = 300\n")

    result = CliRunner().invoke(cli.main, ["check-config", "--config", str(path)])

    assert result.exit_code == 1
    assert "behavior.max_volume" in result.output


def test_init_config_writes_the_example(config_home: Path) -> None:
    result = invoke("init-config")

    assert result.exit_code == 0
    assert f"Wrote {config_home}" in result.output
    assert invoke("check-config").output.startswith(f"{config_home}: valid")


def test_init_config_does_not_overwrite_without_force(config_file: Path) -> None:
    result = CliRunner().invoke(cli.main, ["init-config"])
    assert result.exit_code == 1
    assert "--force" in result.output
    assert config_file.read_text() == CONFIG

    assert invoke("init-config", "--force").exit_code == 0
    assert config_file.read_text() != CONFIG


def test_init_config_writes_to_a_given_path(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b.toml"
    assert invoke("init-config", str(path)).exit_code == 0
    assert path.exists()


# -- the sound server ---------------------------------------------------------------------------------------------


@pytest.mark.usefixtures("audio")
def test_list_devices_marks_the_defaults() -> None:
    lines = invoke("list-devices").output.splitlines()

    assert lines == [
        "Outputs:",
        "  * speaker",
        "      speaker description, 50%, running",
        "    buds",
        "      buds description, 30%, muted",
        "Inputs:",
        "  * mic",
        "      mic description, 80%",
    ]


@pytest.mark.usefixtures("audio", "config_file")
def test_list_apps_tells_which_strip_takes_each_application() -> None:
    lines = invoke("list-apps").output.splitlines()

    assert lines == [
        "  Brave  binary: brave, 100%",
        "      goes to strip 3 (Browser)",
        "  WEBRTC VoiceEngine (shown as 'Discord')  binary: Discord, 60%, paused",
        "      goes to an auto strip",
        "  speech-dispatcher-espeak  binary: -, 100%",
        "      goes to ignored",
    ]


@pytest.mark.usefixtures("audio")
def test_without_auto_strips_an_application_may_get_no_strip(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[[strip]]\ntype = "empty"\n' * 8)

    assert "goes to no strip" in invoke("list-apps", "-c", str(path)).output


def test_list_apps_without_applications(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_audio_state", lambda: AudioState())

    assert invoke("list-apps").output == "No application plays right now.\n"


def test_a_sound_server_that_can_not_be_reached_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unreachable(client_name: str) -> AudioState:
        raise ConnectionRefusedError("no socket")

    monkeypatch.setattr(pulse, "_read_state", unreachable)

    result = CliRunner().invoke(cli.main, ["list-devices"])

    assert result.exit_code == 1
    assert "can't reach the sound server (is pipewire-pulse running?): no socket" in result.output


# -- the device ---------------------------------------------------------------------------------------------------


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

    monkeypatch.setattr(cli, "run_selftest", selftest)

    result = CliRunner().invoke(cli.main, ["test"])

    assert result.exit_code == 1
    assert message in result.output


def test_test_runs_the_selftest_and_ends_quietly_on_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    async def selftest(device_name: str, echo: object, show_events: bool) -> None:
        calls.append((device_name, show_events))
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_selftest", selftest)

    assert invoke("test", "--no-events").exit_code == 0
    assert calls == [("X-Touch-Ext", False)]


# -- running ------------------------------------------------------------------------------------------------------


def test_run_starts_the_daemon_with_the_configuration(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[Config, Path | None]] = []
    levels: list[int] = []

    class FakeDaemon:
        def __init__(self, config: Config, backend: object, config_path: Path | None) -> None:
            started.append((config, config_path))

        async def run(self) -> None:
            pass

    monkeypatch.setattr(cli, "Daemon", FakeDaemon)
    monkeypatch.setattr(systemd, "setup_logging", levels.append)

    assert invoke("run", "-c", str(config_file), "--log-level", "debug").exit_code == 0
    assert started[0][0] == parse_config(CONFIG)
    assert started[0][1] == config_file
    assert levels == [10]


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

        async def __aenter__(self) -> "FakePulse":
            return self

        async def __aexit__(self, *exc: object) -> None:
            pass

    async def snapshot(pulse: object) -> AudioState:
        assert isinstance(pulse, FakePulse)
        return STATE

    monkeypatch.setattr(pulsectl_asyncio, "PulseAsync", FakePulse)
    monkeypatch.setattr(PulseBackend, "snapshot", staticmethod(snapshot))

    assert cli._audio_state() == STATE
    assert clients == ["xtouch-daemon-cli"]


# -- the GUI ------------------------------------------------------------------------------------------------------


def _without_gui_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [name for name in sys.modules if name.startswith("xtouch_daemon.gui")]:
        monkeypatch.delitem(sys.modules, name)


def test_the_gui_starts_with_the_configuration(config_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import xtouch_daemon.gui.qt

    paths: list[Path] = []

    def run_gui(path: Path) -> int:
        paths.append(path)
        return 0

    monkeypatch.setattr(xtouch_daemon.gui.qt, "run_gui", run_gui)

    assert invoke("gui").exit_code == 0
    assert invoke("gui", "-c", "/tmp/other.toml").exit_code == 0
    assert paths == [config_home, Path("/tmp/other.toml")]


def test_the_gui_reports_a_file_it_can_not_edit(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[device")

    result = CliRunner().invoke(cli.main, ["gui", "-c", str(path)])

    assert result.exit_code == 1
    assert f"Error: {path} is not valid TOML" in result.output


@pytest.mark.parametrize("package", ["PyQt6", "qtawesome", "qt_themes", "tomlkit"])
def test_without_the_gui_extra_it_says_how_to_install_it(monkeypatch: pytest.MonkeyPatch, package: str) -> None:
    _without_gui_modules(monkeypatch)
    monkeypatch.delitem(sys.modules, "xtouch_daemon.gui.domain.document", raising=False)
    monkeypatch.setitem(sys.modules, package, None)

    result = CliRunner().invoke(cli.main, ["gui"])

    assert result.exit_code == 1
    assert "the GUI needs the gui extra" in result.output
    assert "uv tool install --force 'xtouch-daemon[gui] @ git+https://github.com/markusressel/xtouch-daemon'" in (
        result.output
    )


def test_a_broken_gui_module_is_not_hidden_behind_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    _without_gui_modules(monkeypatch)
    monkeypatch.setitem(sys.modules, "xtouch_daemon.gui.qt.window", None)

    with pytest.raises(ImportError, match=r"xtouch_daemon\.gui\.qt\.window"):
        invoke("gui")
