from pathlib import Path

import pytest

from tests.test_systemd import FakeSystemctl
from xtouch_daemon.gui.domain.apply import Applied, apply
from xtouch_daemon.systemd import UNIT_NAME, Service

RUNNING = "LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
STOPPED = "LoadState=loaded\nActiveState=inactive\nUnitFileState=enabled\n"


@pytest.fixture
def default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "xtouch-daemon" / "config.toml"


def test_a_running_service_reloads(default_path: Path):
    systemctl = FakeSystemctl(RUNNING)

    applied = apply(Service(systemctl), default_path, device_changed=False)

    assert applied == Applied("Saved and reloaded: the device shows the new configuration.", reloaded=True)
    assert systemctl.commands[-1] == ["systemctl", "--user", "reload", UNIT_NAME]


def test_a_changed_device_takes_a_restart(default_path: Path):
    applied = apply(Service(FakeSystemctl(RUNNING)), default_path, device_changed=True)

    assert applied.reloaded
    assert applied.restart_needed
    assert "restart the service" in applied.message


def test_a_service_that_does_not_run_is_not_reloaded(default_path: Path):
    systemctl = FakeSystemctl(STOPPED)

    applied = apply(Service(systemctl), default_path, device_changed=False)

    assert applied == Applied("Saved. The service is stopped: start it to use the configuration.", reloaded=False)
    assert len(systemctl.commands) == 1


def test_another_file_than_the_one_of_the_service_is_not_applied(default_path: Path, tmp_path: Path):
    systemctl = FakeSystemctl(RUNNING)

    applied = apply(Service(systemctl), tmp_path / "copy.toml", device_changed=False)

    assert applied == Applied(
        f"Saved. The service reads {default_path}, not this file, so it was not reloaded.", reloaded=False
    )
    assert systemctl.commands == []
