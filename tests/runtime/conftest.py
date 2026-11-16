"""
Fixtures of the daemon tests.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.support.daemon import SPEAKER, Notifications
from tests.support.mqtt import FakeBroker
from tests.support.tasks import finish_tasks
from xtouch_daemon import mqtt as mqtt_module
from xtouch_daemon.runtime import daemon as daemon_module


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> Notifications:
    sent = Notifications()

    def notify(*states: str) -> bool:
        sent.append(states)
        return True

    monkeypatch.setattr(daemon_module.systemd, "notify", notify)
    monkeypatch.setattr(daemon_module.systemd, "reloading", lambda: notify("RELOADING=1"))
    return sent


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(SPEAKER)
    return path


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> FakeBroker:
    monkeypatch.setattr(mqtt_module, "RECONNECT_DELAY", 0.001)
    return FakeBroker()
