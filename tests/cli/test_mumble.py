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
