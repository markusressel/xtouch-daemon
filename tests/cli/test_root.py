"""
Not as root: the commands that run something refuse root, the ones that only show something don't.
"""

import os

import pytest

from tests.support.cli import invoke
from xtouch_daemon import cli
from xtouch_daemon.cli.root import ALLOWED_AS_ROOT, REFUSED

GUARDED = sorted(set(cli.main.commands) - ALLOWED_AS_ROOT)


@pytest.fixture
def root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)


def test_the_commands_that_start_the_daemon_or_run_commands_are_guarded() -> None:
    assert {"run", "gui", "test", "check-config", "init-config", "install-service", "virtual-device"} <= set(GUARDED)
    assert set(cli.main.commands) >= ALLOWED_AS_ROOT


@pytest.mark.usefixtures("root")
@pytest.mark.parametrize("command", GUARDED)
def test_root_is_refused_before_the_command_does_anything(command: str) -> None:
    result = invoke(command, *(["x"] if command in ("why", "observe") else []))

    assert result.exit_code == 1
    assert REFUSED in result.output


@pytest.mark.usefixtures("root")
def test_root_still_gets_the_help_the_version_and_the_schema() -> None:
    assert invoke("run", "--help").exit_code == 0
    assert invoke("--version").exit_code == 0
    schema = invoke("schema")
    assert schema.exit_code == 0
    assert schema.output.startswith("{")


def test_the_user_is_not_refused(config_file: object) -> None:
    result = invoke("check-config")

    assert result.exit_code == 0, result.output
    assert REFUSED not in result.output
