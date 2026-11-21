"""
Files of the configuration that other users can change: refused, as OpenSSH's StrictModes does.
"""

import logging
import os
import stat
from pathlib import Path

import pytest

from tests.support.cli import CONFIG
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import load_config
from xtouch_daemon.config.permissions import check_safe, places, problem, warn_if_readable
from xtouch_daemon.config.sections import HomeAssistantConfig, MqttConfig

ME = os.geteuid()


class Status:
    def __init__(self, uid: int, mode: int) -> None:
        self.st_uid, self.st_mode = uid, mode


@pytest.fixture
def config(tmp_path: Path) -> Path:
    directory = tmp_path / "xtouch-daemon"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    path = directory / "config.toml"
    path.write_text(CONFIG)
    path.chmod(0o644)
    return path


def test_a_file_of_the_user_or_root_that_only_they_write_is_safe() -> None:
    assert problem(Path("/x"), Status(1000, stat.S_IFREG | 0o644), 1000) is None
    assert problem(Path("/x"), Status(0, stat.S_IFDIR | 0o755), 1000) is None
    # read and run by others is fine
    assert problem(Path("/x"), Status(1000, stat.S_IFREG | 0o755), 1000) is None


def test_a_file_others_can_write_is_unsafe_and_the_error_says_how_to_fix_it() -> None:
    for mode in (0o664, 0o646, 0o666):
        found = problem(Path("/c/config.toml"), Status(1000, stat.S_IFREG | mode), 1000)
        assert found == (
            "other users can change /c/config.toml, so the daemon does not use it: "
            "fix it with `chmod go-w /c/config.toml`"
        )
    # also root's
    assert problem(Path("/etc"), Status(0, stat.S_IFDIR | 0o775), 1000) is not None


def test_a_file_of_another_user_is_unsafe() -> None:
    found = problem(Path("/c/config.toml"), Status(999998, stat.S_IFREG | 0o644), 999999)

    assert found == (
        "/c/config.toml belongs to 999998, not to you, so the daemon does not use it: "
        "make it yours with `sudo chown 999999 /c/config.toml`"
    )


def test_the_places_are_the_file_and_its_directory_not_the_ones_above(config: Path) -> None:
    assert places(config) == [config.resolve(), config.parent.resolve()]


def test_a_link_is_checked_with_its_target_and_both_directories(config: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = elsewhere / "config.toml"
    link.symlink_to(config)

    assert places(link) == [config.resolve(), config.parent.resolve(), elsewhere.resolve()]


def test_a_safe_configuration_loads(config: Path) -> None:
    check_safe(config)
    assert load_config(config).slots.channels


def test_a_configuration_others_can_change_is_refused(config: Path) -> None:
    config.chmod(0o666)

    with pytest.raises(ConfigError, match=rf"other users can change {config}.*`chmod go-w {config}`"):
        load_config(config)


def test_a_configuration_in_a_directory_others_can_change_is_refused(config: Path) -> None:
    config.parent.chmod(0o777)

    with pytest.raises(ConfigError, match=rf"`chmod go-w {config.parent}`"):
        load_config(config)


def test_the_target_of_a_link_others_can_change_is_refused(config: Path, tmp_path: Path) -> None:
    link = tmp_path / "link.toml"
    link.symlink_to(config)
    config.chmod(0o620)

    with pytest.raises(ConfigError, match=rf"`chmod go-w {config}`"):
        load_config(link)


def test_a_configuration_of_another_user_is_refused(config: Path) -> None:
    with pytest.raises(ConfigError, match="not to you"):
        check_safe(config, euid=ME + 1)


def test_a_place_that_can_not_be_checked_is_refused(config: Path, tmp_path: Path) -> None:
    link = tmp_path / "dangling.toml"
    link.symlink_to(tmp_path / "gone")

    with pytest.raises(ConfigError, match="can't check"):
        check_safe(link)


def test_without_a_file_the_defaults_need_no_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nothing"))

    assert load_config().slots.channels


def test_a_secret_others_can_read_is_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    secret = tmp_path / "password"
    secret.write_text("hunter2\n")
    secret.chmod(0o644)

    with caplog.at_level(logging.WARNING):
        assert MqttConfig(host="b", password_file=secret).resolve_password() == "hunter2"

    assert f"mqtt.password_file: other users can read {secret}. Keep it to you with `chmod go-rw {secret}`" in (
        caplog.text
    )


def test_a_token_others_can_read_is_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    token = tmp_path / "token"
    token.write_text("abc\n")
    token.chmod(0o644)

    with caplog.at_level(logging.WARNING):
        assert HomeAssistantConfig(url="http://ha.test:8123", token_file=token).resolve_token() == "abc"

    assert f"homeassistant.token_file: other users can read {token}" in caplog.text


def test_a_secret_only_the_user_reads_is_no_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    secret = tmp_path / "password"
    secret.write_text("hunter2\n")
    secret.chmod(0o600)

    with caplog.at_level(logging.WARNING):
        warn_if_readable(secret, "mqtt.password_file")
        # a missing one: reading it says what is wrong
        warn_if_readable(tmp_path / "missing", "mqtt.password_file")

    assert not caplog.text
