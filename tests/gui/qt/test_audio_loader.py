"""
Reading the sound server in a thread (`gui/qt/window/audio_loader.py`).
"""

from PyQt6.QtWidgets import QApplication

from xtouch_daemon.audio.model import AudioState
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
