"""
The file changes on disk while the window in Qt Quick is open (an editor, a script, `init-config`): the window reads
it again without unsaved changes, asks with them, and never overwrites it unasked.
"""

import os
from pathlib import Path

from tests.gui.quick.conftest import MakeUi
from tests.support.dialogs import FakeDialogs
from tests.support.gui import CONFIG
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.window.dialogs import OVERWRITE, RELOAD

THEIRS = CONFIG.replace('label = "Speaker"', 'label = "Boxes"')
"""The file as someone else wrote it."""


def label(ui: Ui) -> str:
    return ui.app.editor.document.get(("channel", "out", "label"))


def edit(ui: Ui) -> None:
    ui.app.editor.document.set(("behavior", "max_volume"), 100)
    ui.app.editor.edited()
    ui.settle()


def replace(path: Path, text: str) -> None:
    """As most editors save: a new file in place of the old one."""
    new = path.with_name(f".{path.name}.new")
    new.write_text(text)
    os.replace(new, path)


def test_without_changes_the_window_reads_the_file_again(ui: Ui, path: Path):
    ui.app.showPage("states")
    path.write_text(THEIRS)
    ui.wait_until(lambda: label(ui) == "Boxes")

    assert not ui.app.editor.document.modified
    ui.wait_until(lambda: not ui.shows("disk_bar"))
    assert ui.app.page == "states"
    assert "changed on disk" in ui.app.shell.statusText

    # a replaced file too, also after the watch of the old one ended with it
    replace(path, CONFIG)
    ui.wait_until(lambda: label(ui) == "Speaker")
    replace(path, THEIRS)
    ui.wait_until(lambda: label(ui) == "Boxes")

    # one step to undo: the version before, as changes to save
    ui.app.shell.undo()
    assert label(ui) == "Speaker"
    assert ui.app.editor.document.modified


def test_its_own_save_is_no_change(ui: Ui, dialogs: FakeDialogs):
    edit(ui)
    assert ui.app.shell.save()
    ui.qtbot.wait(500)

    ui.wait_until(lambda: not ui.shows("disk_bar"))
    assert not ui.app.editor.history.can_redo
    assert ui.app.editor.document.get(("behavior", "max_volume")) == 100
    assert dialogs.shown == []


def test_with_changes_the_bar_asks(ui: Ui, path: Path):
    edit(ui)
    replace(path, THEIRS)
    ui.wait_until(lambda: ui.shows("disk_bar"))
    assert label(ui) == "Speaker"
    assert ui.app.shell.diskMessage.startswith("The file changed on disk.")

    ui.grab()
    ui.click("disk_reload")

    ui.wait_until(lambda: not ui.shows("disk_bar"))
    assert (label(ui), ui.app.editor.document.modified) == ("Boxes", False)
    ui.app.shell.undo()
    assert ui.app.editor.document.get(("behavior", "max_volume")) == 100


def test_keep_mine_overwrites_on_save_without_asking(ui: Ui, path: Path, dialogs: FakeDialogs):
    edit(ui)
    # in one step: a file seen half written would ask twice
    replace(path, THEIRS)
    ui.wait_until(lambda: ui.shows("disk_bar"))

    ui.grab()
    ui.click("disk_keep")
    ui.wait_until(lambda: not ui.shows("disk_bar"))
    assert ui.app.shell.save()

    assert dialogs.shown == []
    assert 'label = "Speaker"' in path.read_text()
    assert "max_volume = 100" in path.read_text()


def test_a_save_asks_before_it_overwrites_a_change(ui: Ui, path: Path, dialogs: FakeDialogs):
    edit(ui)
    # before the window noticed
    path.write_text(THEIRS)

    assert not ui.app.shell.save()
    assert path.read_text() == THEIRS
    assert dialogs.shown[-1].startswith("Someone else changed the file")
    assert dialogs.titles[-1] == "The file changed on disk"

    dialogs.pick = RELOAD
    assert not ui.app.shell.save()
    assert (label(ui), ui.app.editor.document.modified) == ("Boxes", False)

    edit(ui)
    path.write_text(CONFIG)
    dialogs.pick = OVERWRITE
    assert ui.app.shell.save()
    assert 'label = "Boxes"' in path.read_text()


def test_a_file_that_can_not_be_read_keeps_the_window_as_it_is(ui: Ui, path: Path):
    path.write_text("[behavior\n")
    ui.wait_until(lambda: ui.shows("disk_bar"))

    assert "can't be read" in ui.app.shell.diskMessage
    assert label(ui) == "Speaker"
    # fixed in the editor: read again
    path.write_text(THEIRS)
    ui.wait_until(lambda: label(ui) == "Boxes")
    ui.wait_until(lambda: not ui.shows("disk_bar"))


def test_a_file_created_on_disk_is_read(make_ui: MakeUi, tmp_path: Path):
    path = tmp_path / "new" / "config.toml"
    ui = make_ui(file=path)
    assert not ui.app.editor.document.exists

    path.parent.mkdir()
    path.write_text(THEIRS)

    ui.wait_until(lambda: ui.app.editor.document.exists)
    assert label(ui) == "Boxes"
