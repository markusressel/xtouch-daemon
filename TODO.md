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
  see `live/`; check how that interacts).

## The Game strip starts at 0 %

The strip of the `game` channel starts at 0 % when a game starts, even though its volume was set to something else
before. Two possible causes, not checked yet:

- Ours: gaming builds a new mixer (the prototype of slots), so the strip is new and has forgotten its volume
  (`AppGroupStrip.group_volume`); until the game has a stream the fader is down ("idle"), then it shows the volume
  the stream starts with. Step 5 of `docs/development/design/channels-states-slots.md` keeps one controller per channel for as
  long as the configuration, which fixes this within a run.
- PipeWire's: WirePlumber restores the volume of a stream by its properties (mostly `application.name`). Games under
  Proton/Wine often have a generic or changing name, so nothing is restored.

Next time a game starts: `pactl list sink-inputs` shows its `application.name` and the volume it starts with. If
PipeWire doesn't restore it, remember the volume per game ourselves.

## AI support

Is there anything we should add to either the daemon or the GUI to help AI work with them?
Or is it enough that we have a config and documentation up online?
If we can avoid implementing features for AI, that would be best, but if there is something that would add real value to a user, it is worth it.
I was able to edit the config to my liking with AI pretty easily, but maybe there is still something to make it easier for less smart models?
