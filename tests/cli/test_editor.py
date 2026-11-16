"""
`gui`.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.cli import invoke
from xtouch_daemon import __version__, cli
from xtouch_daemon.system import systemd


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
