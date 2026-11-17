# TODO

## A simulated device

After the migration to channels, states and slots: a simulated X-Touch Extender for development without the device,
in the GUI and in end-to-end tests. The plan is in `docs/design/device-simulator.md`.

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


## Mumble Disconnects
Mumble disconnected a moment ago, and the faders for it
  disappeared completely, even though mumble played
  "disconnected" sounds, is that expected? I don't think it
  should be, because that means i cannot change the volume of
  the connection sounds.

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

## A built-in pool `devices`

Next to `apps`, `people` and `auto` (see `docs/design/people-slots.md`): outputs and inputs that appear without a
channel of their own (a USB headset, Bluetooth speakers), handed out to the slots that name `devices`, like `apps`
hands out applications. Needs its own design first: what the strip of a device does (volume, mute, Select for the
default device), how it looks, whether `auto` takes devices too, and what happens when a device is unplugged while
it has a slot. The resolver's rules for pools (hand-down, contest, `from`) apply unchanged.
