"""
`mumble-plugin`.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.cli import invoke
from xtouch_daemon import cli
from xtouch_daemon.voip import mumble


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
