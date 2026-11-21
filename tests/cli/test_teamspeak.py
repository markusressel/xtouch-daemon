"""
`teamspeak-plugin`.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.cli import invoke
from xtouch_daemon import cli
from xtouch_daemon.voip import teamspeak

LIBRARY = Path("/share") / teamspeak.LIBRARY_NAME
INSTALLED = Path("/home/me/.ts3client/plugins") / teamspeak.LIBRARY_NAME


@pytest.mark.parametrize(
    ("found", "lines"),
    [
        (
            teamspeak.Setup(LIBRARY, False, INSTALLED, True),
            [f"Plugin: {LIBRARY}", "TeamSpeak: installed", f"In TeamSpeak: {INSTALLED}"],
        ),
        (
            teamspeak.Setup(None, True, None, False),
            ["Plugin: none yet, --build builds it", "TeamSpeak: not found", "In TeamSpeak: not installed (--install)"],
        ),
        (
            teamspeak.Setup(None, False, None, False),
            ["Plugin: none (a release has it, a checkout builds it with cmake and a C compiler)"],
        ),
    ],
)
def test_teamspeak_plugin_tells_what_there_is(
    found: teamspeak.Setup, lines: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(teamspeak, "setup", lambda: found)
    output = invoke("teamspeak-plugin").output.splitlines()
    assert output[: len(lines)] == lines


def test_teamspeak_plugin_builds_and_installs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(teamspeak, "build", lambda: calls.append("build") or LIBRARY)

    def install(rebuild: bool) -> str:
        calls.append(f"install {rebuild}")
        return "Reload All"

    monkeypatch.setattr(teamspeak, "install", install)
    assert invoke("teamspeak-plugin", "--build").output == f"Built {LIBRARY}\n"
    assert invoke("teamspeak-plugin", "--install").output == "Reload All\n"
    assert invoke("teamspeak-plugin", "--install", "--build").output == "Reload All\n"
    assert calls == ["build", "install False", "install True"]

    def fails(rebuild: bool) -> str:
        raise teamspeak.TeamSpeakError("TeamSpeak 3 is not installed")

    monkeypatch.setattr(teamspeak, "install", fails)
    result = CliRunner().invoke(cli.main, ["teamspeak-plugin", "--install"])
    assert result.exit_code == 1
    assert "Error: TeamSpeak 3 is not installed" in result.output
