# Live view

The GUI shows the strips as the device shows them right now, which only the daemon knows. `xtouch-daemon run` serves
that on the Unix socket `$XDG_RUNTIME_DIR/xtouch-daemon.sock` (mode 0600, next to the runtime file of
`system/instance.py`) for as long as it runs (`live/`).

## Snapshots

- **Whole states, one JSON line each.** A client gets the whole state when it connects and again whenever something
  changed, checked 20 times a second (`live.INTERVAL`). A line is about 2 KB; a state rather than changes means a
  client that connects late or misses one needs nothing else. `version` changes when a line means something else; new
  fields are optional with a default, so they keep it.
- **What it has:**
  - the strips: the LCD lines and backlight, the LEDs, the ring, the fader and whether it is touched, the meter. They
    are the `Surface`'s mirror of the device (a `SimulatedDevice`): what reached it, with the motors and meters moving
    as on the device;
  - whether the device, the sound server and the broker are connected, and whether the device is the virtual one;
  - the `fingerprint()` of the configuration in use;
  - `slots` (`SlotsState`): the mode and the one picked by hand; per slot the candidate, channel, pool, member and
    why; per state its value, `since`, `source` and override; per pool the members that wait;
  - `preview`, `simulated` and `features` (what the daemon takes: `mode`, `override`, `play`, `preview`, `situation`).
- **Applied or not.** The fingerprint is a hash of the whole configuration (secrets included). The GUI compares it
  with the one of the saved file, so it can say whether the daemon took the file instead of assuming a reload worked
  (it keeps the old configuration when the new one has errors or a changed `[mqtt]`).

## Requests

A client may send requests, a line of JSON each. Otherwise the GUI changes the daemon through the file and a reload.

| Request | What |
|---|---|
| `{"request": "mode", "mode": "gaming"}` | Picks a mode (`auto` gives it back to the rules, `"+1"` the next). |
| `{"request": "override", "state": "call", "value": "on"}` | Overrides a state (`auto`, `on`, `off`). |
| `{"request": "play", "event": "fader_moved", "strip": 2, "value": 8000}` | A hand from the GUI: taken by the `Surface` as if the device sent it (`Surface.play()`), while a device is connected. Also `fader_touched` (`touched`), `button_pressed` (`button`, its note, and `pressed`), `encoder_turned` (`steps`), `encoder_pressed` (`pressed`). No answer. |
| `StartPreview`, `KeepPreview`, `EndPreview` | The [live preview](#live-preview). |

- **Of the user only.** The daemon takes requests only from processes of its own user (`SO_PEERCRED`: root can connect
  to a socket of mode 0600), in lines of at most `MAX_REQUEST` (1 MiB): a longer one ends the connection.
- **Never in the way.** Clients get only non-blocking writes. One that falls behind by more than `MAX_BUFFER` is
  dropped (it can connect again), and a socket that can't be made is logged: the daemon runs on without the live
  view, whose end doesn't stop it.

The GUI reads the socket with a `QLocalSocket`, without a thread, and connects again while the daemon runs. Without a
daemon it shows what the file would show, and says so.

## Live preview

The GUI can make the daemon run the configuration of its editor before it is saved, and a situation of Simulate
(`gui/qt/live_preview.py`; the daemon's side is `Daemon.preview()`). The design: [Try changes and situations on the
device](../design/try-and-simulate.md).

- **The whole text.** `StartPreview` carries the TOML text the GUI would save (`SlotsDocument.render()`). The daemon
  reads it with `parse_config()`, so the errors are those of `check-config`, and runs it like a reload: a new mixer on
  the same surface, sound server and broker, carrying states, overrides and the mode picked over by id. The file is
  never written. A text with errors, or a changed `[mqtt]`, is answered with the reason, and what runs keeps running.
  The GUI sends 300 ms after the last edit, and only a document without problems.
- **A situation.** `StartPreview` may carry a `situation` (`slots.outcomes.Situation`), with or without a `config`
  (None: the file's). The `SlotEngine` runs it in a second `Simulation` (`what_if`); see the design for the rest.
- **Replies an old GUI ignores.** The daemon answers with lines without `version` (`{"reply": "preview", "ok": ...,
  "message": ...}`), which an older GUI skips like lines of another version. A daemon from before tells no `features`
  and ignores requests, so the GUI keeps its switch off.
- **Always back to the file.** The preview ends with `EndPreview`; when the connection of its client ends; after
  `PREVIEW_TIMEOUT` (10 s) without a request (the GUI sends `KeepPreview` every 3 s, so a window that hangs with its
  connection open ends it too); and when the file is loaded: on a reload, and when the file changes on disk (checked
  every second). The client is told why (`{"reply": "ended", ...}`). The configuration of the file is kept in memory
  (`Daemon.file_config`), so a file that became unusable meanwhile does not keep the preview running.
- **One at a time.** A second client takes the preview over, and the first one is told: the window someone works in
  wins over one that was left open.
- **Visible.** The status line of systemd ends with "previewing unsaved changes of the GUI", the log tells when a
  preview starts and ends and why, and the GUI shows a pill.
- **Home Assistant entities survive it.** A reload removes the entities of removed channels (an empty retained
  discovery message, which also deletes them from the entity registry). A preview doesn't:
  `MqttBridge.set_entities(..., preview=True)` only stops driving the entities it doesn't have, which stay with their
  retained states. The next configuration that is no preview removes what it doesn't have; entities only a preview
  had also lose their retained state, so a preview leaves nothing behind. The mode select gets the modes of the
  preview.
- **Secrets stay with the user.** The text carries the secrets of the file. The GUI sends it only to a daemon of its
  own user (`SO_PEERCRED` on its end too), and the runtime directory is the user's own (`$XDG_RUNTIME_DIR`, or a
  directory of mode 0700 in the temporary directory).
