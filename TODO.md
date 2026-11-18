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
  the stream starts with. Step 5 of `docs/design/channels-states-slots.md` keeps one controller per channel for as
  long as the configuration, which fixes this within a run.
- PipeWire's: WirePlumber restores the volume of a stream by its properties (mostly `application.name`). Games under
  Proton/Wine often have a generic or changing name, so nothing is restored.

Next time a game starts: `pactl list sink-inputs` shows its `application.name` and the volume it starts with. If
PipeWire doesn't restore it, remember the volume per game ourselves.

## Does the "Grid" view really add anything of value?

I feel like it is not helpful, and we should probably remove it. Is there a reason to keep it that makes sense?

## Sidebar buttons

Can we make our main sidebar collapsable into just icons? that
  would probably save some space. Or we make it a floating menu bar
  instead, then we wouldn't waste so many empty space below the 4
  buttons on it, but we would need to ensure no content is
  displayed below it. And it might make more sense to have it next
  to what the selection shows, not next to the device preview,
  since that is always there anyway. And the configuration view
  should also become a window that can be dragged. I don't want to
  turn this into an IDE, but maybe sidebars like in IntelliJ would
  help again here?!

## Documentation per Version/Commit/Release

can our documentation show different git states? so we can show
  the documentation for different versions/tags/commits or the
  repo? If not we should add that.

