import contextlib
import socket
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from tests.conftest import install_package, output, source, stream
from xtouch_daemon import __version__, cli, instance, live, mumble, systemd
from xtouch_daemon.audio import pulse
from xtouch_daemon.audio.model import AudioState, Card, Profile
from xtouch_daemon.config import Config, InheritStripConfig, parse_config
from xtouch_daemon.media import MprisPlayers

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
rec = "off"
solo = "muted"

[[strip]]
type = "apps"
label = "Browser"
match = ["brave", "firefox"]
color = "yellow"

[[strip]]
type = "empty"

[[strip]]
type = "homeassistant"
label = "Lights"

[[strip]]
type = "homeassistant"
id = "desk"
color = "blue"

[mqtt]
host = "broker"
"""

STATE = AudioState(
    outputs=(output("speaker", 50, running=True, card="alsa_card.pci"), output("buds", 30, muted=True)),
    inputs=(source("mic", 80),),
    streams=(
        stream(1, "Brave"),
        stream(2, "WEBRTC VoiceEngine", "Discord", volume=60, corked=True),
        stream(3, "speech-dispatcher-espeak", ""),
    ),
    default_output="speaker",
    default_input="mic",
    cards=(
        Card(
            "alsa_card.pci",
            "output:analog-stereo",
            (Profile("output:analog-stereo", "Analog Stereo Output"), Profile("off", "Off")),
            "Family 17h/19h HD Audio Controller",
        ),
        Card("bluez_card.buds", "a2dp-sink", (Profile("a2dp-sink", "High Fidelity Playback"),)),
    ),
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
        "  1. 'Out' the default output (white, rec: recording, solo: off, encoder: balance)",
        "  2. input mic (white, no meter, rec: off, solo: muted, encoder: balance)",
        "  3. 'Browser' applications brave, firefox (yellow, rec: recording, solo: off, encoder: media)",
        "  4. empty",
        "  5. 'Lights' Home Assistant, entities *.*_strip_5_* (white)",
        "  6. Home Assistant, entities *.*_desk_* (blue)",
        *[
            f"  {number}. the next application that plays (white, rec: recording, solo: off, encoder: pick)"
            for number in range(7, 9)
        ],
    ]


def test_check_config_without_a_file_checks_the_defaults() -> None:
    result = invoke("check-config")

    assert result.exit_code == 0
    assert result.output.startswith("No configuration file, the defaults: valid\n")
    assert "select makes it the default" not in result.output


def test_a_named_device_with_select_says_so(tmp_path: Path) -> None:
    path = tmp_path / "other.toml"
    path.write_text('[[strip]]\ntype = "output"\ndevice = "buds"\nfader = "homeassistant"\n[mqtt]\nhost = "b"\n')

    assert (
        "1. output buds, select makes it the default (white, rec: recording, solo: off, encoder: volume, "
        "fader: homeassistant)" in invoke("check-config", "-c", str(path)).output
    )


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
        "Profiles of alsa_card.pci, Family 17h/19h HD Audio Controller (speaker):",
        "  * output:analog-stereo",
        "      Analog Stereo Output",
        "    off",
        "      Off",
        "Profiles of bluez_card.buds:",
        "  * a2dp-sink",
        "      High Fidelity Playback",
    ]


@pytest.mark.usefixtures("audio", "config_file")
def test_list_apps_tells_which_strip_takes_each_application() -> None:
    lines = invoke("list-apps").output.splitlines()

    assert lines == [
        "  Brave (@browsers)  binary: brave, 100%",
        "      goes to strip 3 (Browser)",
        "  WEBRTC VoiceEngine (shown as 'Discord') (@voip)  binary: Discord, 60%, paused",
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
    sockets: list[Path] = []
    levels: list[int] = []

    class FakeDaemon:
        def __init__(
            self,
            config: Config,
            backend: object,
            config_path: Path | None,
            live_socket: Path,
            players: object,
            layout_file: Path,
        ) -> None:
            started.append((config, config_path))
            sockets.append(live_socket)
            # what it remembers, in the state directory of the user
            assert layout_file == instance.layout_file()
            assert layout_file.parent.name == "xtouch-daemon"
            # the media players of the session
            assert isinstance(players, MprisPlayers)

        async def run(self) -> None:
            pass

    monkeypatch.setattr(cli, "Daemon", FakeDaemon)
    monkeypatch.setattr(systemd, "setup_logging", levels.append)

    assert invoke("run", "-c", str(config_file), "--log-level", "debug").exit_code == 0
    assert started[0][0] == parse_config(CONFIG)
    assert started[0][1] == config_file
    assert sockets == [instance.socket_file()]
    assert levels == [10]


def test_run_says_that_it_runs_and_a_second_one_does_not_start(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[instance.Instance | None] = []

    class FakeDaemon:
        def __init__(
            self,
            config: Config,
            backend: object,
            config_path: Path | None,
            live_socket: Path,
            players: object,
            layout_file: Path,
        ) -> None:
            pass

        async def run(self) -> None:
            seen.append(instance.running())

    monkeypatch.setattr(cli, "Daemon", FakeDaemon)
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
    # as if it was not installed: its modules that are imported already too
    for name in [name for name in sys.modules if name.startswith(f"{package}.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, package, None)

    result = CliRunner().invoke(cli.main, ["gui"])

    assert result.exit_code == 1
    assert "the GUI needs the gui extra" in result.output
    assert "install the package xtouch-daemon-gui-bin" in result.output
    assert "uv tool install --force './xtouch-daemon[gui]'" in result.output


def test_a_broken_gui_module_is_not_hidden_behind_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    _without_gui_modules(monkeypatch)
    monkeypatch.setitem(sys.modules, "xtouch_daemon.gui.qt.window", None)

    with pytest.raises(ImportError, match=r"xtouch_daemon\.gui\.qt\.window"):
        invoke("gui")


def test_run_reports_a_password_that_is_not_there(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd, "setup_logging", lambda level: None)
    path = tmp_path / "mqtt.toml"
    path.write_text(f'[mqtt]\nhost = "broker"\npassword_file = "{tmp_path / "missing"}"\n')

    result = CliRunner().invoke(cli.main, ["run", "-c", str(path)])

    assert result.exit_code == 1
    assert "mqtt.password_file: can't read" in result.output


def test_the_installed_version_is_the_one_on_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    import xtouch_daemon

    assert xtouch_daemon.installed_version() == __version__
    # after an upgrade
    monkeypatch.setattr(xtouch_daemon, "version", lambda name: "9.9.9")
    assert xtouch_daemon.installed_version() == "9.9.9"


# -- layouts ----------------------------------------------------------------------------------------------------------


def test_check_config_shows_the_layouts(tmp_path: Path) -> None:
    path = tmp_path / "layouts.toml"
    path.write_text(
        '[[strip]]\ntype = "output"\n[voip]\n'
        '[[layout]]\nname = "gaming"\nlabel = "Gaming"\napps = ["steam"]\nprocesses = ["mumble", "ts3"]\npriority = 2\n'
        '[[layout.strip]]\ntype = "inherit"\n[[layout.strip]]\ntype = "voip"\n'
        '[[layout.strip]]\ntype = "voip"\nperson = ["Ann", "ann-phone"]\nlabel = "Mum"\ncollapse = true\n'
        '[[layout.strip]]\ntype = "voip"\nperson = "Bob"\n'
        '[[layout]]\nname = "plain"\n[[layout]]\nname = "music"\napps = ["spotify"]\n'
    )
    lines = invoke("check-config", "-c", str(path)).output.splitlines()
    gaming = lines.index("Layout gaming (Gaming), while steam has a stream or mumble or ts3 runs, priority 2:")
    assert lines[gaming + 1].startswith("  1. the default output")
    assert lines[gaming + 1].endswith("), from the default layout, strip 1")
    assert lines[gaming + 2] == "  2. a participant of the voice chat, in the group (white, talking: green)"
    assert (
        lines[gaming + 3]
        == "  3. 'Mum' Ann or ann-phone in the voice chat, dark while away (white, talking: green, collapses)"
    )
    assert lines[gaming + 4] == "  4. Bob in the voice chat, dark while away (white, talking: green)"
    assert "Layout plain:" in lines
    assert "Layout music, while spotify has a stream:" in lines
    config = parse_config('[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\n')
    assert cli.describe_strip(config.layouts[0].strips[0], 1) == "the strip of the default layout at this place"
    other = InheritStripConfig(type="inherit", layout="voice", strip="music")
    assert cli.describe_strip(other, 1) == "strip music of layout voice"


def test_check_config_tells_where_inherited_strips_come_from(tmp_path: Path) -> None:
    path = tmp_path / "inherit.toml"
    path.write_text(
        '[[strip]]\ntype = "output"\n[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "empty"\n'
        '[[layout.strip]]\ntype = "inherit"\n[[layout]]\nname = "b"\n[[layout.strip]]\ntype = "inherit"\n'
        'layout = "a"\nstrip = 1\n'
    )
    lines = invoke("check-config", "-c", str(path)).output.splitlines()
    a = lines.index("Layout a:")
    assert lines[a + 2].endswith("encoder: pick), from the default layout, an auto strip")
    assert lines[lines.index("Layout b:") + 1] == "  1. empty, from layout a, strip 1"


class FakeLive:
    """
    A daemon's live view on a socket in a thread: tells its layouts, and switches on a request (if `obeys`, otherwise
    it hangs up). `refuses` answers it with the reason why not, like the daemon does for a layout it does not have.
    """

    def __init__(
        self,
        path: Path,
        layouts: tuple[str, ...],
        obeys: bool = True,
        answers: bool = True,
        refuses: str | None = None,
        features: tuple[str, ...] = live.FEATURES,
    ):
        self.path = path
        self.layout = layouts[0] if layouts else None
        self.layouts = layouts
        self.obeys = obeys
        self.answers = answers
        self.refuses = refuses
        self.features = features
        self.requests: list[live.Request] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _line(self) -> bytes:
        snapshot = live.Snapshot(
            "abc", True, True, None, (), features=self.features, layout=self.layout, layouts=self.layouts
        )
        return live.encode(snapshot)

    def _serve(self) -> None:
        connection, _ = self.server.accept()
        with connection, connection.makefile("rb") as lines:
            if not self.answers:
                lines.readline()
                return
            # an older line first, which the client skips
            connection.sendall(b'{"version": 0}\n' + self._line())
            for line in lines:
                request = live.decode_request(line)
                self.requests.append(request)
                assert isinstance(request, live.SwitchLayout)
                if not self.obeys:
                    return
                if self.refuses is not None:
                    reply = live.Reply("layout", False, self.refuses)
                else:
                    self.layout = request.layout
                    reply = live.Reply("layout", True, request.layout)
                with contextlib.suppress(OSError):
                    # a snapshot may come before the reply
                    connection.sendall(self._line() + live.encode_reply(reply))

    def close(self) -> None:
        self.server.close()
        self.thread.join(2)


@pytest.fixture
def live_socket(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="xtc-") as directory:
        path = Path(directory) / "live.sock"
        monkeypatch.setattr(instance, "socket_file", lambda: path)
        yield path


def test_layout_lists_the_layouts(live_socket: Path) -> None:
    fake = FakeLive(live_socket, ("default", "gaming"))
    assert invoke("layout").output.splitlines() == ["* default", "  gaming"]
    fake.close()


def test_layout_of_a_daemon_without_layouts(live_socket: Path) -> None:
    fake = FakeLive(live_socket, ())
    assert invoke("layout").output.splitlines() == ["  default"]
    fake.close()


@pytest.mark.parametrize(
    ("args", "wanted"),
    [(("gaming",), "gaming"), (("--next",), "gaming"), (("--previous",), "voice"), (("default",), "default")],
)
def test_layout_switches_the_daemon(live_socket: Path, args: tuple[str, ...], wanted: str) -> None:
    fake = FakeLive(live_socket, ("default", "gaming", "voice"))
    assert invoke("layout", *args).output == f"Layout {wanted}\n"
    fake.close()
    assert fake.requests == [live.SwitchLayout(wanted)]


def test_layout_reports_what_goes_wrong(live_socket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = CliRunner().invoke(cli.main, ["layout"])
    assert result.exit_code == 1
    assert "the daemon does not run" in result.output

    fake = FakeLive(live_socket, ("default", "gaming"))
    result = CliRunner().invoke(cli.main, ["layout", "nope"])
    assert "there is no layout nope (default, gaming)" in result.output
    fake.close()
    live_socket.unlink()

    fake = FakeLive(live_socket, ("default", "gaming"), obeys=False)
    result = CliRunner().invoke(cli.main, ["layout", "gaming"])
    assert "the daemon did not switch to gaming" in result.output
    fake.close()
    live_socket.unlink()

    fake = FakeLive(live_socket, ("default", "gaming"), refuses="There is no layout gaming (default)")
    result = CliRunner().invoke(cli.main, ["layout", "gaming"])
    assert "Error: There is no layout gaming (default)" in result.output
    fake.close()
    live_socket.unlink()

    # one from before the requests of the live view
    fake = FakeLive(live_socket, ("default", "gaming"), features=())
    result = CliRunner().invoke(cli.main, ["layout", "gaming"])
    assert "the daemon is older than this program, restart it" in result.output
    fake.close()
    live_socket.unlink()

    monkeypatch.setattr(cli, "LAYOUT_TIMEOUT", 0.05)
    fake = FakeLive(live_socket, ("default",), answers=False)
    result = CliRunner().invoke(cli.main, ["layout"])
    assert "the daemon did not answer" in result.output
    fake.close()


def test_check_config_shows_what_select_launches() -> None:
    config = parse_config(
        '[voip]\n[[strip]]\ntype = "apps"\nmatch = ["mumble"]\nlabel = "VoIP"\n'
        'launch = ["mumble", "mumble://me@example.org/Gaming Night"]\n'
        '[[strip]]\ntype = "auto"\nlaunch = "spotify"\nlaunch_when_running = true\n'
        '[[strip]]\ntype = "voip"\nlaunch = ["mumble"]\n'
    )
    apps, auto, voip = config.strips[:3]
    assert cli.describe_strip(apps, 1) == (
        "'VoIP' applications mumble, select launches mumble 'mumble://me@example.org/Gaming Night' while it does "
        "not run (white, rec: recording, solo: off, encoder: media)"
    )
    assert "the next application that plays, select launches spotify also while it runs (" in cli.describe_strip(
        auto, 2
    )
    assert cli.describe_strip(voip, 3).endswith(", select launches mumble while it is not there")


# -- the Mumble plugin --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("found", "lines"),
    [
        (
            mumble.Setup(Path("/b.mumble_plugin"), False, Path("/p/libxtouch-daemon.so"), True),
            ["Plugin: /b.mumble_plugin", "Mumble: installed", "In Mumble: /p/libxtouch-daemon.so"],
        ),
        (
            mumble.Setup(None, True, None, False),
            ["Plugin: none yet, --build builds it", "Mumble: not found", "In Mumble: not installed (--install)"],
        ),
        (
            mumble.Setup(None, False, None, False),
            ["Plugin: none (a release has it, a checkout builds it with cmake and a C compiler)"],
        ),
    ],
)
def test_mumble_plugin_tells_what_there_is(
    found: mumble.Setup, lines: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mumble, "setup", lambda: found)
    output = invoke("mumble-plugin").output.splitlines()
    assert output[: len(lines)] == lines


def test_mumble_plugin_builds_and_installs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mumble, "build", lambda: calls.append("build") or Path("/b.mumble_plugin"))

    def install(rebuild: bool) -> str:
        calls.append(f"install {rebuild}")
        return "Mumble asks"

    monkeypatch.setattr(mumble, "install", install)
    assert invoke("mumble-plugin", "--build").output == "Built /b.mumble_plugin\n"
    assert invoke("mumble-plugin", "--install").output == "Mumble asks\n"
    assert invoke("mumble-plugin", "--install", "--build").output == "Mumble asks\n"
    assert calls == ["build", "install False", "install True"]

    def fails(rebuild: bool) -> str:
        raise mumble.MumbleError("Mumble is not installed")

    monkeypatch.setattr(mumble, "install", fails)
    result = CliRunner().invoke(cli.main, ["mumble-plugin", "--install"])
    assert result.exit_code == 1
    assert "Error: Mumble is not installed" in result.output


def test_check_config_describes_choices_and_strips_that_collapse(tmp_path: Path) -> None:
    path = tmp_path / "flow.toml"
    path.write_text(
        '[[strip]]\ntype = "output"\nchoices = [{ label = "Phones", device = "a" },'
        ' { label = "Speaker", device = "b" }, { device = "bluez_output.*" }]\n'
        '[[strip]]\ntype = "output"\ndevice = "bluez_output.*"\ncollapse = true\n'
        + '[[strip]]\ntype = "auto"\n' * 6
        + '[voip]\nprovider = "demo"\n[[strip]]\ntype = "voip"\ncollapse = true\n'
    )
    output = invoke("check-config", "-c", str(path)).output
    assert "  1. output: Phones, Speaker or bluez_output.* (Select switches) (white, rec: recording" in output
    assert "  2. output bluez_output.*, select makes it the default (white, rec: recording, solo: off, " in output
    assert "encoder: balance, collapses)" in output
    assert "  9. a participant of the voice chat, in the group (white, talking: green, collapses)" in output
    assert "  The device shows the first 8 of them that don't collapse." in output


def test_check_config_shows_what_presets_stand_for(tmp_path: Path) -> None:
    path = tmp_path / "presets.toml"
    path.write_text(
        '[[strip]]\ntype = "apps"\nmatch = ["@video", "netflix"]\nlabel = "Video"\n'
        '[[layout]]\nname = "gaming"\napps = ["@steam-games", "minecraft"]\nprocesses = ["@steam-games"]\n'
    )
    lines = invoke("check-config", "-c", str(path)).output.splitlines()
    assert lines[1].startswith(
        "  1. 'Video' applications @video (vlc, mpv, celluloid, totem, kodi, haruna, clapper, mplayer), netflix ("
    )
    assert (
        "Layout gaming, while @steam-games (steam_app_, .exe, wine-preloader, wine64-preloader) or minecraft has a "
        "stream or @steam-games (reaper) runs:" in lines
    )
