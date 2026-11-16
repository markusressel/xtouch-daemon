# TODO

## GUI: notice changes of the configuration file on disk

The GUI reads the file once when it opens and never again. If the file changes while the GUI is open (an editor, a
script, `init-config`), "Save and apply" writes the GUI's old version over those changes.

- Watch the file with `QFileSystemWatcher`, on its directory, not the file itself: editors and the GUI's own save
  replace the file (new inode), which a watch on the file loses.
- Ignore the GUI's own saves (compare the content with what it wrote).
- Without unsaved changes in the GUI: reload quietly, keep the selected strip, layout and tab.
- With unsaved changes: a bar "The file changed on disk" with **Reload** (discards the edits) and **Keep mine**.
- On save: check whether the file changed since it was read (content or mtime); if so, ask instead of overwriting.
- A reload is one step in the undo history.
- The live preview: a reload while it runs sends the new document (the daemon ends a preview when the file changes,
  see `live.py`; check how that interacts).
