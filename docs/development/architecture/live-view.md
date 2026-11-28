# Live view

The GUI shows the strips as the device shows them right now, which only the daemon knows. `xtouch-daemon run` serves
that on the Unix socket `$XDG_RUNTIME_DIR/xtouch-daemon.sock` (mode 0600, next to the runtime file of
`system/instance.py`) for as long as it runs (`live/`).

## Snapshots

- **Whole states, one JSON line each.** A client gets the whole state when it connects and again whenever something
  changed. A line is about 2 KB; a state rather than changes means a client that connects late or misses one needs
  nothing else. `version` changes when a line means something else; new fields are optional with a default, so they
  keep it.
- **Pushed, not polled.** Nothing runs on a timer: what changes a snapshot calls `LiveServer.changed()` (the
  `Surface` for every message to and from the device and its connection, the sound server, the voice chat, each step
  of the slots, the MQTT bridge, the requests, a reload and the end of a preview). The snapshot goes out once the
  event loop is through with what it does at that moment, so what changes together goes out together, as often as
  things change. One that tells nothing new (see below) is not sent. The views of the twins go out the same way, from
  their own surfaces and steps; reality reaches a twin when it changes.
- **What moves by itself is told once.** A meter is sent with the level it was set to and when (`meter_at`), a fader
  that glides with its position, speed and target then (`Glide`), as `time.monotonic()`, which is the same clock in
  the GUI on this machine. The GUI draws the fall and the glide at the rate of the screen (`meter_now()`,
  `fader_now()`, the same steps as the daemon's motor drive, `hardware.strip.glide_step()`); a snapshot that differs
  only in where a glide is now (`steady()`) is not sent. So a moving fader costs a line when it starts and one when it
  arrives, a meter a line per peak (10 a second while it plays), a dark meter none.
- **What it has:**
  - the strips: the LCD lines and backlight, the LEDs, the ring, the fader and whether it is touched, the meter. They
    are the `Surface`'s mirror of the device (a `SimulatedDevice`): what reached it, with the motors and meters moving
    as on the device;
  - whether the device, the sound server and the broker are connected, and whether the device is the virtual one;
  - the `fingerprint()` of the configuration in use;
  - `slots` (`SlotsState`): the mode and the one picked by hand; per slot the candidate, channel, pool, member and
    why; per state its value, `since`, `source` and override; per pool the members that wait;
  - `sounding`: the ids of the channels with sound right now (`slots/sounding.py`), from what the sound server and
    the voice chat tell: an output or input that is running, an `apps` channel with a stream that is not paused, a
    `person` who talks. The GUI animates them; an animation runs on its own clock, so it costs no lines;
  - `preview`, `simulated` and `features` (what the daemon takes: `mode`, `override`, `play`, `preview`, `situation`,
    `on_device`, `test`, `log`).
- **The devices it saw.** A line of its own, `{"known_devices": [...]}` (`KnownDevices`), when a client connects (if
  there are any) and whenever they change: every output and input the sound server had, with its card, the profile
  the card was in and when it was there last (`daemon/device_memory.py`, kept in `devices.json` of the state
  directory, forgotten after 90 days). The GUI suggests them while they are not there; the CLI skips the line.
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
| `{"request": "forget_device", "name": "bluez_output.1", "direction": "output"}` | Forgets a device it saw (Delete in the list of the GUI). The clients get the devices again. No answer. |
| `StartPreview`, `KeepPreview`, `EndPreview` | The [live preview](#live-preview). |
| `StartTest`, `KeepTest`, `EndTest` | The test of the device (`hardware/selftest.py`): the `Surface` lends the test its own strips (`Surface.lend()`), the strips of the slots keep what is drawn on them without showing it until `take_back()`. Answered with a `Reply` of kind `test`; `test_ended` tells why the daemon ended it (timeout `TEST_TIMEOUT`, device gone, a preview on the device, another client). The snapshot says `test`. |

| `{"request": "watch_log"}`, `{"request": "end_log"}` | The [log](#log) of the daemon, for the window Log of the GUI. |

- **Of the user only.** The daemon takes requests only from processes of its own user (`SO_PEERCRED`: root can connect
  to a socket of mode 0600), in lines of at most `MAX_REQUEST` (1 MiB): a longer one ends the connection.
- **Never in the way.** Clients get only non-blocking writes. One that falls behind by more than `MAX_BUFFER` is
  dropped (it can connect again), and a socket that can't be made is logged: the daemon runs on without the live
  view, whose end doesn't stop it.

The GUI reads the socket with a `QLocalSocket`, without a thread, and connects again while the daemon runs. Without a
daemon it shows what the file would show, and says so.

## Log

The window Log of the GUI shows the log of the daemon, whether it runs as the service (the journal) or in a terminal
(`live/log.py`). The design: [The log in the GUI](../design/log-viewer.md).

- **Kept in memory.** `xtouch-daemon run` attaches a `LogBuffer` to the root logger before anything else: a
  `logging.Handler` that keeps the latest `LOG_SIZE` (1000) records as `LogEntry` (`seq`, `time`, `level`, `logger`,
  `message` with its traceback), the ones the terminal or the journal get, at the daemon's `--log-level`.
- **Sent while watched.** `WatchLog` gets the records kept, as a line `{"log": [...], "backlog": true}`, then every
  new one in lines `{"log": [...]}`, until `EndLog` or the end of the connection. The `LiveServer` handles both
  requests itself, not the daemon (`LogRequest`; the daemon's are `DaemonRequest`). The GUI asks only while its window
  Log shows, and again on a new connection; a backlog starts it over.
- **Cheap when nobody watches.** A record costs its message and a place in a deque. With a watcher the buffer calls
  `LiveServer._logged()`, which goes through `call_soon_threadsafe` (other threads log too, e.g. `system/launch.py`)
  and sends what came since in one line per client, once the event loop gets to it. A client that falls behind is
  dropped as for the snapshots; `seq` shows a gap if records left the buffer before they were sent.
- **Of the user only**, like the requests: the log may name files, devices and people of the user. The daemon never
  logs secrets (the MQTT password is a `SecretStr`).

## Virtual twin

The preview "In the GUI" runs on a twin per client (`daemon/twin.py`, `Daemon.preview_on_twin()`). `Twin` and
`Daemon` are both a `Rig` (`daemon/rig.py`: the `Desk`, `SlotEngine` and `SlotMixer` of a configuration on one
surface, and the loop that steps them). The twin's rig is on a `Surface(port=NoPort())`, an in-memory `TwinBackend` and
a `DemoProvider` as voice chat. It is built from the `Config` and the real `Names` (applications, people, devices, used
as stand-ins first) only, so it touches nothing real. Its mode and overrides come from the situation only: the chord,
controls and requests change nothing on it (`SlotEngine.fixed`). `slots/world.py` turns a `Situation` into its sound
server and people (`world()`); without a situation the twin runs the world of now by its names (`world_of_now()`) with
the real mode and states (`Daemon._situation_now()`), and follows them. Its view goes as a separate line
`{"twin": ...}` to its client only (`LiveServer.tell_view`); `Play(event, preview=True)` is a hand on it.

## Live preview

The GUI can make the daemon run the configuration of its editor before it is saved, and a situation of Simulate, on
the device or on a twin of its own (`gui/qt/live_preview.py`; the daemon's side is `Daemon.preview()` and
`Daemon.preview_on_twin()`). The design: [Previews, in the GUI or on the device](../design/previews.md).

- **The whole text.** `StartPreview` carries the TOML text the GUI would save (`SlotsDocument.render()`). The daemon
  reads it with `parse_config()`, so the errors are those of `check-config`, and runs it like a reload: a new mixer on
  the same surface, sound server and broker, carrying states, overrides and the mode picked over by id. The file is
  never written. A text with errors, or a changed `[mqtt]`, is answered with the reason, and what runs keeps running.
  The GUI sends 300 ms after the last edit, and only a document without problems.
- **Where.** `StartPreview.on_device` (true for a GUI of 0.1.0, which knows no other place): on the device, or on
  the client's twin. Sent again to the other place, the preview moves: the twin ends, or the device runs the file
  again. `KeepPreview` and `EndPreview` cover both.
- **A situation.** `StartPreview` may carry a `situation` (`slots.outcomes.Situation`), with or without a `config`
  (None: the file's). The `SlotEngine` runs it in a second `Simulation` (`what_if`); see the design for the rest.
- **Replies an old GUI ignores.** The daemon answers with lines without `version` (`{"reply": "preview", "ok": ...,
  "message": ...}`), which an older GUI skips like lines of another version. A daemon from before tells no `features`
  and ignores requests, so the GUI keeps its preview off.
- **Always back to the file.** The preview ends (on the device, and the twin) with `EndPreview`; when the connection of its client ends; after
  `PREVIEW_TIMEOUT` (10 s) without a request (the GUI sends `KeepPreview` every 3 s, so a window that hangs with its
  connection open ends it too); and when the file is loaded: on a reload, and when the file changes on disk (checked
  every second; a twin goes on, it doesn't use the file). A twin also ends when its task fails. The client is told
  why (`{"reply": "ended", ...}`). The configuration of the file is kept in memory
  (`Daemon.file_config`), so a file that became unusable meanwhile does not keep the preview running.
- **One on the device at a time.** A second client takes the device over, and the first one is told: the window
  someone works in wins over one that was left open, and goes back to its twin. Twins: one per client, no limit.
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
