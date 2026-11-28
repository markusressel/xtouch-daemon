"""
Reading the sound server in a thread (`gui/qt/window/audio_loader.py`).
"""

from collections.abc import Callable

import pytest
from PyQt6.QtWidgets import QApplication

from xtouch_daemon.audio.model import DISCONNECTED, AudioState
from xtouch_daemon.gui.qt.window.audio_loader import AudioLoader


def test_a_read_that_fails_in_any_way_ends_with_it(qapp: QApplication):
    def broken() -> AudioState:
        raise ValueError("bad reply")

    failed: list[str] = []
    loader = AudioLoader(broken)
    loader.failed.connect(failed.append)
    loader._run()  # pyright: ignore[reportPrivateUsage]
    # the window would say it reads the sound server for good
    assert failed == ["ValueError: bad reply"]


def test_following_tells_each_state_and_a_lost_sound_server_and_ends_after_stop(qapp: QApplication):
    loaded: list[AudioState] = []
    failed: list[str] = []
    loader = AudioLoader(AudioState)
    loader.loaded.connect(loaded.append)
    loader.failed.connect(failed.append)
    told: list[str] = []

    def follow(on_state: Callable[[AudioState], None]) -> None:
        on_state(AudioState())
        on_state(DISCONNECTED)
        loader.stop()
        on_state(AudioState())
        told.append("never")

    loader._follow(follow)  # pyright: ignore[reportPrivateUsage]
    assert loaded == [AudioState()]
    assert len(failed) == 1
    assert "lost the sound server" in failed[0]
    assert told == []


def test_following_that_fails_ends_it(qapp: QApplication, caplog: pytest.LogCaptureFixture):
    def broken(on_state: Callable[[AudioState], None]) -> None:
        raise ValueError("bad reply")

    AudioLoader(AudioState)._follow(broken)  # pyright: ignore[reportPrivateUsage]
    assert "Following the sound server failed" in caplog.text
