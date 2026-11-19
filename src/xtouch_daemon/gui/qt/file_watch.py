"""
Notices changes of the configuration file on disk while the window is open: an editor, a script or `init-config`
writing it. `changed` only says that something happened to the file or next to it; whether its text is another one
than the window read decides `SlotsDocument.changed_on_disk()`.
"""

from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal

REST_MS = 200
"""How long the file rests before `changed`: a save of an editor is several events (write, rename, chmod...)."""


class FileWatch(QObject):
    """
    Watches the file and its directory. The file itself for a write in place (which leaves the directory alone), the
    directory for a file that is replaced (a new inode, as most editors save: the watch of the file ends with the old
    one) or created. While the directory is not there yet, the closest one above it that is. A symbolic link is
    followed to the file it points to.
    """

    changed = pyqtSignal(arguments=[])

    def __init__(self, path: Path, parent: QObject | None = None):
        super().__init__(parent)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
        self.path = path
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._event)
        self.watcher.directoryChanged.connect(self._event)
        self.rest = QTimer(self)
        self.rest.setSingleShot(True)
        self.rest.setInterval(REST_MS)
        self.rest.timeout.connect(self._rested)
        self._watch()

    def _watch(self) -> None:
        """Watches what is there now: a replaced file, a link that points elsewhere, a directory that was created."""
        target = self.path.resolve()
        directory = target.parent
        while not directory.is_dir() and directory != directory.parent:
            directory = directory.parent
        # the file anew each time: a watch of a file that was replaced may still be listed, on the old inode
        if files := self.watcher.files():
            self.watcher.removePaths(files)
        if target.is_file():
            self.watcher.addPath(str(target))
        directories = self.watcher.directories()
        if directories != [str(directory)]:
            if directories:
                self.watcher.removePaths(directories)
            self.watcher.addPath(str(directory))

    def _event(self, _path: str) -> None:
        self.rest.start()

    def _rested(self) -> None:
        self._watch()
        self.changed.emit()
