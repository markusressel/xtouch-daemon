from pathlib import Path

import pytest

from tests.support.instance import RecordingInstance
from xtouch_daemon.gui.domain.apply import Applied, apply


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


@pytest.fixture
def service(path: Path) -> RecordingInstance:
    return RecordingInstance(1234, path.resolve(), systemd=True)


def test_the_running_daemon_reloads(service: RecordingInstance, path: Path):
    applied = apply(service, path)

    assert applied == Applied("Saved and reloaded: the device shows the new configuration.", reloaded=True)
    assert service.reloads == [1234]


def test_a_daemon_started_elsewhere_reloads_too(path: Path):
    daemon = RecordingInstance(4242, path.resolve(), systemd=False)

    applied = apply(daemon, path)

    assert daemon.reloads == [4242]
    assert applied == Applied("Saved and reloaded: the device shows the new configuration.", reloaded=True)


def test_a_changed_mqtt_section_is_not_reloaded(service: RecordingInstance, path: Path):
    # the daemon would keep the whole old configuration
    applied = apply(service, path, ("mqtt",))

    assert applied == Applied(
        "Saved. The [mqtt] section changed: restart the service to use the configuration.",
        reloaded=False,
        restart_needed=True,
    )
    assert service.reloads == []


def test_nothing_is_reloaded_without_a_daemon(path: Path):
    assert apply(None, path) == Applied(
        "Saved. The daemon is not running: start it to use the configuration.", reloaded=False
    )


def test_another_file_than_the_one_of_the_daemon_is_not_applied(service: RecordingInstance, tmp_path: Path):
    applied = apply(service, tmp_path / "copy.toml")

    assert applied == Applied(f"Saved. The service reads {service.config}, not this file.", reloaded=False)
    assert service.reloads == []
