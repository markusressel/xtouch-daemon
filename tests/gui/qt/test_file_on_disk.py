"""
The file changes on disk while the window is open (an editor, a script, `init-config`): the window reads it again
without unsaved changes, asks with them, and never overwrites it unasked.
"""

import os
from pathlib import Path

from pytestqt.qtbot import QtBot

from tests.support.gui import CONFIG, Dialogs, MakeWindow
from xtouch_daemon.gui.qt.window.main_window import MainWindow

THEIRS = CONFIG.replace('label = "Speaker"', 'label = "Boxes"')
"""The file as someone else wrote it."""


def label(window: MainWindow) -> str:
    return window.document.get(("channel", "out", "label"))


def edit(window: MainWindow) -> None:
    window.document.set(("behavior", "max_volume"), 100)
    window.editor.edited()


def replace(path: Path, text: str) -> None:
    """As most editors save: a new file in place of the old one."""
    new = path.with_name(f".{path.name}.new")
    new.write_text(text)
    os.replace(new, path)


def test_without_changes_the_window_reads_the_file_again(qtbot: QtBot, window: MainWindow, path: Path):
    window.show_page("states")
    path.write_text(THEIRS)
    qtbot.waitUntil(lambda: label(window) == "Boxes")

    assert not window.document.modified
    assert not window.disk_bar.isVisible()
    assert window.current_page == "states"
    assert "changed on disk" in window.status.text()

    # a replaced file too, also after the watch of the old one ended with it
    replace(path, CONFIG)
    qtbot.waitUntil(lambda: label(window) == "Speaker")
    replace(path, THEIRS)
    qtbot.waitUntil(lambda: label(window) == "Boxes")

    # one step to undo: the version before, as changes to save
    window.undo()
    assert label(window) == "Speaker"
    assert window.document.modified


def test_its_own_save_is_no_change(qtbot: QtBot, window: MainWindow, path: Path, isolated: Dialogs):
    edit(window)
    assert window.save()
    qtbot.wait(500)

    assert not window.disk_bar.isVisible()
    assert not window.history.can_redo
    assert window.document.get(("behavior", "max_volume")) == 100
    assert isolated.shown == []


def test_with_changes_the_bar_asks(qtbot: QtBot, window: MainWindow, path: Path):
    edit(window)
    replace(path, THEIRS)
    qtbot.waitUntil(window.disk_bar.isVisible)
    assert label(window) == "Speaker"

    window.reload_button.click()

    assert not window.disk_bar.isVisible()
    assert (label(window), window.document.modified) == ("Boxes", False)
    window.undo()
    assert window.document.get(("behavior", "max_volume")) == 100


def test_keep_mine_overwrites_on_save_without_asking(qtbot: QtBot, window: MainWindow, path: Path, isolated: Dialogs):
    edit(window)
    path.write_text(THEIRS)
    qtbot.waitUntil(window.disk_bar.isVisible)

    window.keep_button.click()
    assert not window.disk_bar.isVisible()
    assert window.save()

    assert isolated.shown == []
    assert 'label = "Speaker"' in path.read_text()
    assert "max_volume = 100" in path.read_text()


def test_a_save_asks_before_it_overwrites_a_change(window: MainWindow, path: Path, isolated: Dialogs):
    edit(window)
    # before the window noticed
    path.write_text(THEIRS)

    assert not window.save()
    assert path.read_text() == THEIRS
    assert isolated.shown[-1].startswith("Someone else changed the file")

    isolated.pick = "Reload"
    assert not window.save()
    assert (label(window), window.document.modified) == ("Boxes", False)

    edit(window)
    path.write_text(CONFIG)
    isolated.pick = "Overwrite"
    assert window.save()
    assert 'label = "Boxes"' in path.read_text()


def test_a_file_that_can_not_be_read_keeps_the_window_as_it_is(qtbot: QtBot, window: MainWindow, path: Path):
    path.write_text("[behavior\n")
    qtbot.waitUntil(window.disk_bar.isVisible)

    assert "can't be read" in window.disk_message.text()
    assert label(window) == "Speaker"
    # fixed in the editor: read again
    path.write_text(THEIRS)
    qtbot.waitUntil(lambda: label(window) == "Boxes")
    assert not window.disk_bar.isVisible()


def test_a_file_created_on_disk_is_read(qtbot: QtBot, make_window: MakeWindow, tmp_path: Path):
    path = tmp_path / "new" / "config.toml"
    window = make_window(file=path)
    assert not window.document.exists

    path.parent.mkdir()
    path.write_text(THEIRS)

    qtbot.waitUntil(lambda: window.document.exists)
    assert label(window) == "Boxes"
