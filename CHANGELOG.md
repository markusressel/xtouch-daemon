# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

- A virtual X-Touch Extender, for the daemon without the device: `xtouch-daemon run --virtual-device` (or
  `[device] virtual = true`) drives it on a Unix socket instead of the real one, `xtouch-daemon virtual-device` runs
  it headless (`--broken-touch 1,4`), and the GUI opens it from the pill while the daemon waits for it: the mouse on
  the drawing is a hand on it (faders with and without a touch, buttons, encoders), a bar unplugs it, switches it off
  and on and breaks touch sensors. It speaks the bytes of the device, and does what the device does as far as
  [Hardware](docs/hardware.md#the-virtual-device) knows. The live view shows the daemon's mirror of the device (the
  same model), so the GUI draws what reached the device, banners and flashes included, with the motors and meters
  moving as on it. See `docs/design/device-simulator.md`.
- Channels, states and slots (see the page Channels, states and slots and `docs/design/channels-states-slots.md`):
  `[channel.*]` say what a strip can control, `[state.*]` what goes on (a call, a game, a mode), and `[slots]` what
  each of the 8 strips shows, as candidates with conditions (`"voip if call"`, `"mum if present"`). A slot gets
  another strip when what it shows changes, the others stay as they are (no blank texts), a slot that shows another
  candidate flashes its label and why (`gaming`, `not call`) for `switching.banner` seconds, `[controls]` claim the
  fader, encoder and buttons of a slot whatever it shows (a launch, a mode, a state toggled by hand, Home
  Assistant), and the chord (Solo of strips 1 and 8 held together) picks the next mode or does another action
  (`chord = { strips = [1, 8], action = "toggle:call" }`: `cycle_modes`, `mode:<id>`, `toggle:<state or mode>`). A
  file without `[slots]` shows `auto` on every slot; `[pool.apps] exclude` leaves out `speech-dispatcher` by
  default, `min_volume` and `max_volume` of channels and `apps` and `auto` slots are checked, and `launch` on a `person`
  channel is an error (`[controls]` does that). `check-config` prints the table of the slots, `init-config` writes
  an example, `xtouch-daemon mode` lists and picks the modes, `xtouch-daemon why <slot or channel>` tells why a slot
  shows what it does, `xtouch-daemon simulate` what the slots show in given states, `xtouch-daemon observe` records
  what plays and runs, and `simulate --replay` replays such a recording through a configuration. With `[mqtt]`, Home
  Assistant gets `select.<ns>_mode`, a binary sensor per state (`since`, `source`, `override`), an override select
  per state, an input switch per state with `homeassistant = true`, `binary_sensor.<ns>_<channel>_shown` and
  `sensor.<ns>_slot_<n>` (what the slot shows, with `label`, `kind`, `via` and `reason`). The live view tells the
  mode, the states and what each slot shows and why, and takes requests to pick a mode and to override a state; the
  GUI shows the mode in a pill next to the preview, with the states and slots in its tooltip.
  The GUI edits this format: a rail with the pages Slots (the states, to override or pick, and a card per slot
  with its candidates, their conditions as chips and ▶ on the one shown, to add, remove, drag or move with
  Ctrl+Up/Down; the inspector edits what a candidate shows, when and the options of its place, says where else its
  channel is used, and lists the controls of the slot; above it the why line: why the slot shows what it does,
  which `xtouch-daemon why <slot or channel>` tells too; Simulate shows with a frame around the device what the
  slots would show in another mode, with other states on or channels absent, without sending anything (Esc ends it)), Channels (the channels, `[pool.apps]`,
  `[pool.people]` and `[pool.auto]`, with Add, Duplicate and Remove, and where each is used), States (modes first, their sources,
  delays and where they are used, what the daemon says about each, an override or a mode picked) and Settings. Problems lead to their channel, state or setting.
- Presets: named groups of well-known applications for the lists that match applications by name, e.g.
  `match = ["@browsers"]` or `processes = ["@steam-games"]`, next to names of one's own. `@browsers`, `@voip`,
  `@steam-games`, `@games`, `@music` and `@video` work in `match` of `apps` channels, `apps` and `processes` of states
  and `exclude` of `[pool.apps]`, each with the names of the streams or of the processes of its applications (e.g. Steam's
  `reaper` for `@steam-games` in `processes`). An unknown preset, or one in a list it is not for, is an error that says
  what fits. `check-config` shows what each one stands for, `list-apps` the presets of each application that plays
  (`Brave (@browsers)`), and the GUI suggests the presets that fit a list, with what they stand for as the tooltip.
  See the new page Presets.
- `choices` on `output` and `input` strips: one strip for several devices used one at a time, each maybe in a
  profile of its sound card (`card`, `profile`), with a label and a volume range of its own. Select goes to the next
  one that is there: it switches the card's profile first if needed, then makes the device the default; the label
  shows at once, a failed switch goes back, quick presses step through. The strip follows a default changed
  elsewhere. With `[mqtt]`, `select.<ns>_<id>_output` (`_input`) chooses in Home Assistant. `check-config`
  describes it ("output: Phones, Speaker or Buds (Select switches)").
- GUI: `choices` with the devices, cards and profiles to pick from per line.
- `list-devices` shows the description of each sound card next to its name.
- `launch` on `apps` and `auto` channels: Select starts the command (a list, or one string split like a shell
  would, never through a shell) while the strip's application does not run, e.g. Mumble with a `mumble://` URL that
  joins a channel. "Runs" counts processes too (a silent Mumble), the Select LED flashes while it starts and is on
  while it runs. It starts as a transient systemd user service, so a restart of the daemon does not end it.
  `launch_when_running` starts it always (`apps`, `auto`). `check-config` shows it, the GUI edits it.
- The people of a voice chat on the strips: one per strip, the name on the LCD, lit in `talking_color` while they
  talk, the fader for their volume and Mute to mute them. They sit on the slots that show `people`, and share
  those of `auto` with the applications (`[pool.people] from` and `order`). A `person` channel (a name, or several names of one person, ignoring case) keeps a
  person on a strip, shown dark with `away` while they are not there (`label` names it). The daemon keeps the
  volume and mute set for each name and sets them again when the person comes back. `[voip]` picks where they come from: `bridge`, a
  plugin of the voice chat client on the socket `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock` (the protocol is in the
  documentation, versioned), or `demo` people who talk in turns.
- A `[voip]` section is optional: without one the people come from its defaults (the `bridge` provider).
- A Mumble plugin (`integrations/mumble`, Mumble 1.4 and later) for the strips of people: the people of your channel, who
  talks and how loud, the fader for their volume (the plugin's own, on top of Mumble's local volume) and Mute for
  Mumble's local mute (shown in Mumble; a local mute set in Mumble lights the button). "Install Mumble plugin" on the GUI's page "Voice chat" (or `xtouch-daemon mumble-plugin --install`)
  hands it to Mumble's installer, building it first in a checkout; the page lists the steps and tells whether Mumble
  is connected. Releases ship the plugin in `/usr/share/xtouch-daemon/`, CI builds it.
- The live view tells the names of the voice chat's participants and who is on which strip.
- `just screenshot` renders the screenshots of the README and the documentation (docs/images/) offscreen, with a
  demo configuration and device, so they can be updated with the GUI.
- "Live preview" in the GUI: while it is on, the device runs the configuration in the editor before it is saved
  and follows every change. Saving keeps it; turning it off, closing the window, or a window that crashed or hangs
  brings back the file, and so does a change of the file on disk or a reload. Errors of the daemon show inline. It needs a daemon of this version (restart an older
  one), which takes previews only from its own user. It sits next to Save and apply as "Try on the device", only
  while there are unsaved changes, with a pill that says what the device runs (the saved file, the changes, or what
  is wrong).

- `lit_when_idle` on audio strips: the LCD keeps its backlight while the strip has nothing to control, e.g. an
  `apps` group whose applications don't play.
- The GUI explains every option without the documentation: the help names the default, a choice says what the
  chosen value does (e.g. `recording` for the Rec LED, each value also as a tooltip in the list), a strip type what
  it controls, and "Learn more" links open the matching section of the documentation.
- `behavior.max_volume` is 130 by default: 100 % sits at the 0 dB mark of the faders (77 % of the travel), and
  the top 23 % amplify up to 130 %, with one slope over the whole travel. `max_volume = 100` puts 100 % at the top
  again.
- Arch Linux packages in the AUR: `xtouch-daemon-bin` (the daemon with its own Python 3.14, the systemd user unit
  `/usr/lib/systemd/user/xtouch-daemon.service` and the example configuration) and `xtouch-daemon-gui-bin` (the GUI
  on the system's PyQt6, `xtouch-daemon-gui`, with a menu entry), built from the release tarballs on GitHub.
- `install-service` of the package takes the unit of the package instead of writing one;
  `install-service --remove-override` removes a unit in `~/.config/systemd/user` that overrides it.
- The GUI shows which unit runs the service ("packaged", or the program of a unit in `~/.config/systemd/user`),
  removes one that overrides the package's ("Use the packaged unit"), and highlights Restart when the daemon runs
  another version than the one installed, e.g. after an upgrade.
- The live view tells the version of the daemon.
- The GUI's window Device shows the device on every page: docked above the page at first, at any side, or as a
  window of its own (e.g. on another screen), kept for the next start; View → Device closes and opens it. The
  strips keep pictures of themselves, so they draw about ten times faster while it changes size, also while the
  live view moves their meters and faders; they are drawn sharp once the size stays.
- Handles between the two panes of the pages Slots, Channels and States: the form of what is picked has most of the
  width at first, and each page keeps its share.
- Previews of the controls in the GUI: the options of a channel are in cards by the part of the strip (encoder,
  display, buttons, fader and meter), each with a drawing of that part that shows what the options do on the
  device in a few steps (‹ and ›), each with a caption, e.g. which LEDs light while an application records, or whether the meter stays up while
  the fader goes down (`meter_point`).
- Colors for states (violet), channels (teal) and slots (orange) in the whole GUI, in both themes: the icons of
  their pages, the chips on the cards of the slots, the state bar, and the words and sections in the help.
- Shorter help for the options, written for someone at the device: what changes there first, short sentences,
  details behind "Learn more". The rules are in `AGENTS.md` (Writing help).
- The condition of a candidate (When, on the page Slots) is a code field: states violet, channels in `present(...)`
  teal, keywords bold, a mistake (an unknown state, a condition that ends too early) underlined in red with what is
  wrong in its tooltip, and the words that fit offered while typing (Ctrl+Space: all of them). The candidate the
  device shows has a green dot instead of ▶, which read as "opens"; the options of its place show with their
  values (`color = white`) instead of their names alone. Shows and When have help, with "Learn more" to the
  slots and to the new section [Conditions](docs/configuration/slots.md#conditions), which documents the grammar of
  conditions.
- The form of a state asks in order: State or Mode (label and priority only for a mode), then On while: Sources
  (only those it has, Add source for more, ✕ to remove one) or Condition (the field of the page Slots, without
  `present`), never both. Delays and overrides are folded away until a state has one. A state whose last option
  is removed stays (it was removed with it).
- On the cards of the page Slots, `present` is spelled out in what it means for the channel or pool (`when browser plays
  → browser`, `mic is connected`, `mum is in the voice chat`) in a color of its own (olive), apart from the teal of what
  the slot shows, and chips of one condition are joined by "or". Conditions are outlined chips, what the slot shows
  filled ones. A rail joins the candidates of a card ("else" between two, numbered, a green node on the one shown);
  above it they are dimmed with why they did not win, below it as not reached. A pool without a condition reads `when
  app without a slot → apps` (an outlined chip), and a tiny LCD after each candidate has the color its strip gets (its
  own, the channel's or the pool's). A slot whose pools have no member left ends its rail in "nothing to show: the strip
  is dark" instead of marking the last pool as shown; `xtouch-daemon why` says `shows nothing: people has none left` and
  `simulate` `- (dark: people has none left)`. The chip of the pool shown names its member (`apps · firefox`), its
  tooltip who waits; cards grow and shrink smoothly.
- Three built-in pools: `apps` (the applications that play and have no slot), `people` (the people of the voice
  chat) and `auto` (both, sharing its slots, people first). A slot says where people sit:
  `5 = ["people", "apps"]` is a person, else the next application; a pool with no member for a slot hands it to the
  pool or `-` right below it, and a slot two pools could fill goes to the one higher in its stack. `from` sets the
  side each fills from (`[pool.people]` from the right, `[pool.apps]` from the left by default). `[people]` is
  `[pool.people]` now, `hold` and `exclude` moved from `[pool.auto]` to `[pool.apps]`, `in_auto` is `in_pool`;
  `check-config` names the old spellings. `present(apps)` and `present(people)` work in conditions,
  `present(auto)` holds while either does. `check-config` notes candidates that never show and people that can
  sit nowhere, `xtouch-daemon why people` tells who sits where and who waits, and the GUI's Simulate takes a
  number of people in the call and of applications that play. See `docs/design/people-slots.md`.
- Select and Play above the drawing of the device in the GUI. Select: dragging a strip moves its slot (candidates and
  controls) to another place, the others glide aside, as do Ctrl+Left/Right and the context menu. Play: the mouse is a
  hand on the device, on the virtual device the GUI hosts or on the device of a running daemon, which takes a new
  live-view request `play` as if the device sent the event. "Try without a device" starts a daemon with the virtual
  device and opens it in the window while no daemon runs.
- Simulate on the device: with "Try on the device" on, the GUI's Simulate runs on the device too (real or virtual),
  with its delays and dwells, real applications, people and devices as stand-ins first and made-up ones for the rest,
  and Play works on it. The switch is there while Simulate is open, the pill says "On the device · simulated", and
  Home Assistant never sees the situation. `StartPreview` takes a `situation` and no `config` (the file's), snapshots
  tell `simulated`. See `docs/design/try-and-simulate.md`.
- The GUI's pages are a window Configuration, like the window Device: each docks at any side or floats as a window of
  its own (e.g. on another screen). Its rail shows icons only, » shows their names.
- The GUI's pills moved to what they are about: "Live" and the mode ("Mode: gaming", "No mode") to the bar of the
  window Device, Home Assistant into the pill of the service, which tells the worst problem of the daemon's
  connections (device, sound server, Home Assistant, voice chat); a click on it lists them with their settings.
- The GUI's title names the file (• with unsaved changes) instead of a line in the header.
- Help in the GUI without waiting for tooltips: the footer shows the first sentence of the tooltip under the mouse at
  once (tooltips follow after 300 ms), pills with ▾ open their details on a click (the pill next to Save with the
  path of the file, Live, the mode with the states and buttons to pick one), and Play and "Try on the device" say
  next to them why they are off. A popover has a row per thing with a bar in the color of how it does (a problem
  also tinted, its fix as the main button), states in their color, `code` and paths in a monospace font.
  Popovers are drawn inside the window: they no longer grab the keyboard and the mouse, so screenshot tools and the
  keys of the window manager keep working while one is open.
  Tooltips have a slimmer frame and the colors of the help: states, channels and slots in their colors, `code` in a
  monospace font, what follows the first paragraph muted.
- The states above the cards of the slots open a popover instead of a menu: what turned the state on, its override
  (marked as real: the device and Home Assistant follow it) and "Simulate it off/on" from the situation there is.
- What the GUI read from the sound server is a pill: a click lists the outputs, inputs and applications, or why it
  couldn't, with "Read again" (the popover stays open and shows what it read).
- Popovers are titled with what they are about ("Connections", "Mode and states", "Sound server") and don't repeat
  the pill that opened them.
- Simulate, the states and the sound server share one row above the slots; Simulate comes first and stays where it
  is while the what-ifs replace the states.
- "Learn more" opens the documentation of the installed version; addresses without a version (older links) and of
  versions not published yet go to the same page of the latest documentation instead of "not found".
- The inspector of a slot says it plainly: a pool with no member on a slot is "no application on a slot" (or
  nobody, no device, no person or application), members without `app:`, the controls line what `[controls]` claims
  of the slot or that it claims none, and the help of a pool that the candidate below gets the slot it can't fill.
  `xtouch-daemon why` words pools the same way.
- The inspector of a slot starts with the path of its candidates (`Slot 3 › 1 games › 2 apps`, the one it shows
  with a dot, a click picks one) instead of "Slot 3 · candidate 2", then a box of what goes on: why it shows what it
  shows a step a line, what the candidate shows and where it is now, and `[controls]`. The form comes after it.
- Dragging the handle between the panes of a page no longer lags: where it was left is written once, when it is let
  go, not on every move.
- An icon: four strips of the device (encoders, LCDs, faders), in the README, the documentation and the GUI's header
  and window, and of the desktop file of `xtouch-daemon-gui-bin`.
- The documentation has a version per release (and `dev` for main) with a version selector, built once per version
  with mike to the branch `gh-pages`; `just docs-at <ref>` serves the documentation of any commit locally.
- A built-in pool `devices`: the outputs and inputs no channel has (a USB headset, Bluetooth speakers), on the slots
  that name `devices`, each as the `output` or `input` strip of that device. A channel without `device` has the
  default device of its direction. `[pool.devices]` takes `from` (left by default), `exclude` (node names or
  descriptions), `hold` (5 s a device keeps its slot after it went away) and the look of an output strip; `auto`
  doesn't take devices. `present(devices)` works in conditions, and the GUI's Simulate takes a number of devices.
- A menu bar in the GUI: File (Save and apply, Revert, Quit), Edit (Undo, Redo), View (the window Device, the theme,
  the zoom) and Help (the documentation).
- "Stop" in the header of the GUI while the service runs: stops it, but leaves it enabled.
- The strips of the GUI look like the device: the ring has 13 LEDs, the LCD is a negative display (the backlight
  shines around a dark panel and through its characters and the line between its two lines), the meter has 8 LEDs next to the buttons (REC, SOLO and MUTE square, SELECT wider), whose names are printed under them,
  and the faders are longer, with the dB scale of the device: the middle of the cap marks the value, -∞ at the
  bottom, 0 dB at 77 % of the travel and +10 dB at the top.
  The meter lights its LEDs for a level as the device does (7 for the loudest audio, the red CLIP LED when it clips).
- GUI zoom, 67..300 %: Ctrl++ / Ctrl+= larger, Ctrl+- smaller, Ctrl+0 100 %, and View → Zoom. It scales
  the whole window, the strips too, and is kept for the next start.
- `number.<ns>_<id>_meter` on `homeassistant` strips: Home Assistant sets the LED meter, 0..100 %, and the daemon
  holds the level.
- The GUI shows the connection to Home Assistant: a pill next to the preview while the daemon uses `[mqtt]`
  (connected, or what is wrong: not authorized, refused, unknown host, unreachable), the same with details on the
  page "Home Assistant", and "Test connection", which tries the settings in the editor before they are saved.
- 100 % at the 0 dB mark of the faders (about 77 % of the travel, `behavior.unity_at`) on strips that go above
  100 %: the travel above the mark covers the amplification. The faders of such strips were linear.
- `[device] startup` and `shutdown`: how the strips light up after a connect and go dark at the end: `instant`,
  `sweep` (one after the other, the default), `curtain` (from the middle outwards, and back) or `show` (a wave of
  light: white backlights, buttons, meters and filling rings).
- The encoder shows the exact value of what it did on the LCD for 2 s: the balance (`L 15%`, `center`), the
  position in the track (`1:05`), `playing`/`paused`, which application of how many (`2/5`), `pinned`/`auto`, the
  number in Home Assistant.
- `[device] touchless_faders`: faders whose touch sensor failed work without it: a move counts as a touch, half a
  second without a move as letting go.
- `[device] touch_required = false`: every move of a fader counts, as on `touchless_faders`, e.g. a fingertip
  pushing a fader from below, which the touch sensor does not notice.
- Strip types `output` and `input` (a device, several with Select switching between them, e.g. any Bluetooth
  headphones with `bluez_output.*`, or the default one; Select makes it the default), `apps` (all streams of
  a group of applications), `auto` (the next application that plays) and `empty`.
- `profiles` on `output` and `input` strips: Rec switches the sound card between profiles, e.g. analog and digital
  output; the label of the active profile names the strip (e.g. "Phones" and "Speaker"), and the new device
  becomes the default if the old one was. `list-devices` lists the profiles of the cards.
- `min_volume` and `max_volume` on strips and profiles: the range of the fader, up to 200 % (also
  `behavior.max_volume`, which was limited to 150 %).
- `encoder` on strips: what the encoder does; `balance` (left/right, a push centers it) is the default for devices,
  `volume` the fine steps of the volume.
- `encoder = "pick"`, the default for `auto` strips: the encoder picks the application, a push pins it.
- `encoder = "media"`, the default for `apps` strips: the media player of the applications (MPRIS over D-Bus):
  turning seeks 5 s per step, a push plays or pauses, the ring fills up with how far the track is (blinking while
  paused, dark while stopped). A paused player keeps the strip active after its streams are gone, until it is
  stopped or closed.
- `encoder = "homeassistant"` and `fader = "homeassistant"` on audio strips: one control is a number entity in Home
  Assistant (e.g. a light), the other one sets the volume. `id` names the entities.
- Motor faders that glide smoothly (also after a connect, from the bottom), follow changes made elsewhere, stay still
  while touched, and get their value again after arriving so the motor doesn't stop short. Strips with nothing to
  control (an application that ended, a device that is gone, the daemon stopping) put their faders away slowly.
- Startup and shutdown sequences: the strips light up one after the other from the left after a connect, and go dark
  from the right when the daemon stops.
- LCD labels, volume and state on a backlight in the strip's color; Mute LED; encoder for fine steps, push to reset.
- Passive LED meters from `pw-record` captures.
- Strip type `homeassistant`: the fader, encoder, LCD lines and color, LEDs and button events of a strip become
  Home Assistant entities over MQTT discovery (`[mqtt]` section), for automations.
- Rec and Solo LEDs as configurable indicators (`rec`, `solo`): recording, playing, default, muted. By default Rec is
  lit while an application records the device, or while the applications of the strip record.
- Reconnects to the device and the sound server.
- systemd user service with `Type=notify`, reload on SIGHUP, journal log levels, and a dark surface on shutdown.
- Commands `run`, `check-config`, `init-config`, `list-devices`, `list-apps`, `test` and `install-service`.
- `xtouch-daemon gui` (extra `gui`): edits the configuration in a window with a preview of the eight strips (click to
  edit, drag to move), suggestions from the sound server, the errors next to the options, and the comments of the file
  kept on saving. It reloads the running daemon after saving (the service, or one started from a terminal or an IDE),
  and shows, installs, starts and restarts the service.
- `xtouch-daemon run` notes its process and configuration file in `$XDG_RUNTIME_DIR/xtouch-daemon.json` while it runs,
  and a second one does not start.
- The GUI shows the strips live, as the device shows them (LCDs, LEDs, rings, faders, meters), from the running
  daemon, which serves them on `$XDG_RUNTIME_DIR/xtouch-daemon.sock`, and says whether the device runs the saved file.
  Global settings have a tab of their own, apart from the options of the selected strip. A dragged strip leaves its
  place and the others make room (Escape cancels); strips also move with Ctrl+arrows and their context menu, to any of
  the 8 places. Removing a strip leaves an `auto` strip in its place, so the others stay where they are. Every edit
  can be undone (Ctrl+Z), also removing a strip and reverting the file.
- A clip indicator: when the audio of a strip peaks at full scale, its meter lights all 8 LEDs, the red one at the
  top too, for half a second. Below that, the meter uses 7 LEDs. The `homeassistant` meter entity reaches the red LED
  at 100 %.
- `meter_point`: whether the meters show the level before the volume and Mute of a strip (`"pre_fader"`, the
  default, like the channel meters of a hardware mixer) or after them (`"post_fader"`). Set in `[behavior]`, per
  channel and per place in a slot; the place wins over the channel, the channel over `[behavior]`. The monitor of an output is before its volume (so its pre-fader meter is what it was
  before, and post-fader multiplies by the volume); streams and inputs apply their volume and Mute in their own
  PipeWire node, so their pre-fader level is the captured one divided by the volume, and a muted stream or input
  stays dark either way. On the strips of people the Mumble plugin tells the level before and after the participant's
  volume; a muted participant who talks lights the meter before the fader (Mumble doesn't fetch their voice). The
  GUI shows it next to `meter` and on the behavior page; `check-config` names post-fader meters.
- A documentation site (Zensical, published to GitHub Pages): getting started, a page per topic of the
  configuration, Home Assistant, the GUI, every command, troubleshooting, hardware and architecture.

[0.1.0]: https://github.com/markusressel/xtouch-daemon/releases/tag/v0.1.0

### Fixed

- The GUI window jumped around when it opened and the first time a candidate of a slot was picked: the help of
  every option showed as a window of its own for a moment, and the desktop made room for each. The window also
  opens at a size the screen has room for, and the drawing of the device gets smaller (down to about a third), so
  the window fits on smaller screens and at a larger zoom.
- The GUI window grew wider while it was open: longer texts in the header and the footer (the path with
  "unsaved changes", the status, the sound server) and more state buttons on the page Slots made it need more
  width. Those texts now end in … where they don't fit (the whole text is the tooltip), and the state bar scrolls
  sideways. Picking a candidate of a slot no longer builds its options again, and the cards of the slots and the
  list of the channels are only built again when they change.
- The list of a choice in the GUI was too short for two values and hid one: it now opens under the field, with
  room for every value.
- "Save and apply" in the GUI stayed off for a file changed outside the GUI, so the daemon could not be told to
  take it: it is now on while the daemon runs another version of the file, and then only reloads it.
- The mouse wheel over a number, a choice or a slider in the GUI changed its value while scrolling the page; it now
  scrolls the page.
- Selecting a strip in the GUI built its whole page again, so the options jumped around several times per click,
  and the live view laid out the window about 40 times a second. The pages are now built once and only take the
  new values; the options of a strip are in the order of the device, from the encoder down to the fader.
- A fader dragged to a new value jumped back to where it was before when it was let go, while the volume stayed at
  the new value (the device moves a released fader to the value it got last).
- The ring of `encoder = "balance"` flickered while the fader moved: it went dark after every change of the
  volume until the sound server reported it.
- The meters came up to 64 ms late, by a different amount per strip (pw-record buffered its output): two
  meters of the same audio now move together.
- After the device was switched off and on again, the faders stayed at the bottom: they come up to their values
  again.
- The meter of an output that was the default followed the default to the next output after Select (WirePlumber
  makes such a capture follow the default); meters now stay with their device.
- A balance a hair off the center lit only the center LED of the ring, like an exact center.
- Volumes above 153 % (`max_volume` up to 200) ended at 153 %: pulsectl limits volumes to where the sliders of
  pavucontrol end.
