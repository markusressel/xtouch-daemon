"""
Fixtures of the command line tests.
"""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.cli import CONFIG, STATE
from xtouch_daemon.cli import sound as sound_commands
from xtouch_daemon.system import instance


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
    monkeypatch.setattr(sound_commands, "_audio_state", lambda: STATE)


@pytest.fixture
def live_socket(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="xtc-") as directory:
        path = Path(directory) / "live.sock"
        monkeypatch.setattr(instance, "socket_file", lambda: path)
        yield path
