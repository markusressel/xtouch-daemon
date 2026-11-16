"""
The command: its help and version.
"""

from tests.support.cli import invoke
from xtouch_daemon import __version__


def test_the_version_is_shown() -> None:
    assert invoke("--version").output.strip().endswith(__version__)


def test_without_a_command_the_help_is_shown() -> None:
    result = invoke()
    assert "Use a Behringer X-Touch Extender as a hardware mixer for PipeWire." in result.output
