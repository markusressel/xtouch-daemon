# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

- Prototype of channels, states and slots (`docs/design/channels-states-slots.md`), the planned successor of
  layouts, `inherit` and `collapse`: `xtouch-daemon simulate` shows what the slots of a configuration in that
  format show in given states, and why; `xtouch-daemon observe` records what plays and runs, and
  `simulate --replay` replays such a recording through a configuration. The daemon runs a file in that format too
  (`[channel.*]`, `[state.*]`, `[slots]` instead of strips and layouts), for trying it on the device: a slot gets
  another strip when what it shows changes, the others stay as they are (no blank texts), a slot that shows another
  candidate flashes its label and why (`gaming`, `not call`) for `switching.banner` seconds, `[controls]` claim the
  fader, encoder and buttons of a slot whatever it shows (a launch, a mode, a state toggled by hand, Home Assistant),
  layout switches by hand pick a mode, the chord can do another action (`chord = { strips = [1, 8], action =
  "toggle:call" }`: `cycle_modes`, `mode:<id>`, `toggle:<state or mode>`), and `check-config` prints its table.
  With `[mqtt]`, Home Assistant gets `select.<ns>_mode` (instead of the layout select), a binary sensor per state
  (`since`, `source`, `override`), an override select per state, an input switch per state with
  `homeassistant = true`, `binary_sensor.<ns>_<channel>_shown` and `sensor.<ns>_slot_<n>` (what the slot shows,
  with `label`, `kind`, `via` and `reason`). The live view tells the mode, the states and what each slot shows and
  why, takes requests to pick a mode and to override a state, and the GUI shows the mode in a pill next to the
  preview, with the states and slots in its tooltip.
- Presets: named groups of well-known applications for the lists that match applications by name, e.g.
  `match = ["@browsers"]` or `processes = ["@steam-games"]`, next to names of one's own. `@browsers`, `@voip`,
  `@steam-games`, `@games`, `@music` and `@video` work in `match` of `apps` strips, `apps` and `processes` of layouts
  and `behavior.ignore`, each with the names of the streams or of the processes of its applications (e.g. Steam's
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
- Collapsing strips: `collapse = true` on `output`, `input`, `apps`, `auto` and `voip` strips gives the strip's fader
  to the strips after it while it has nothing to control (after `behavior.collapse_hold`, 3 s), and it comes back at
  once. A configuration (or layout) may list up to 32 strips; the device shows the first 8 that take a place. Strips
  move with everything they show, never while a fader is touched or a button held, and each move is logged.
  `check-config` reports strips that could never get a fader. The live view tells the placement.
- `inherit` strips take any strip of any layout: `layout` names the layout, `strip` the strip in its list (from 1)
  or its `id`. Chains resolve (up to 8), loops and unknown layouts, strips and ids are errors. The strip carries all
  its options (`collapse`, `launch`, a `voip` strip its `person`), and a Home Assistant strip keeps the entities of
  its own place. `check-config` tells where each inherited strip comes from; the GUI picks the layout and the strip
  and previews the strip referred to.
- GUI: `choices` with the devices, cards and profiles to pick from per line; a strip list that reaches the strips
  beyond the 8 of the device, tells where each one is (on the device, collapsed, waiting) and adds strips while they
  could get a place. The preview follows the strips that moved.
- `list-devices` shows the description of each sound card next to its name.
- Layouts: `[[layout]]` sections with their own `[[layout.strip]]` lists, e.g. one for games; the top-level strips
  are the layout `default`, so existing files work as before. The device switches with `xtouch-daemon layout NAME`
  (`--next`, `--previous`), the Home Assistant entity `select.<ns>_layout`, Solo of strips 1 and 8 held together
  (`switching.chord`), or rules: `apps` (while an application has a stream) and `processes` (while a process runs),
  with `priority` and `switching.hold`. The LCDs show the label of the layout that comes (`switching.banner`).
  `check-config` lists every layout, and the entities of `homeassistant` strips of all layouts stay in Home
  Assistant.
- The daemon remembers the layout across restarts (in `~/.local/state/xtouch-daemon/layout`), unless a rule put it
  there; a rule that matches at the start still wins. Home Assistant's select follows the daemon, a retained state of
  the last run no longer switches the layout.
- `launch` on `apps`, `auto` and `voip` strips: Select starts the command (a list, or one string split like a shell
  would, never through a shell) while the strip's application does not run, e.g. Mumble with a `mumble://` URL that
  joins a channel. "Runs" counts processes too (a silent Mumble), the Select LED flashes while it starts and is on
  while it runs. It starts as a transient systemd user service, so a restart of the daemon does not end it.
  `launch_when_running` starts it always (`apps`, `auto`). `check-config` shows it, the GUI edits it.
- `inherit` strips: in a layout, the strip of the default layout at the same place.
- `voip` strips: the participants of a voice chat, one per strip, the name on the LCD, lit in `talking_color` while
  they talk, the fader for their volume and Mute to mute them. `person` (a name, or several names of one person,
  ignoring case) keeps a person on a strip, shown dark with `away` while they are not there (`label` names it). The
  other `voip` strips of a layout are its group, wherever they are: they fill with the participants without a strip
  of their own, and Select on any of them pages through more participants than strips. A name on two strips of a
  layout is an error. The daemon keeps the volume and mute set for each name and sets them again when the person
  comes back. `voip` strips with the same `launch` start it once. `[voip]` picks where they come from: `bridge`, a
  plugin of the voice chat client on the socket `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock` (the protocol is in the
  documentation, versioned), or `demo` people who talk in turns.
- A `[voip]` section is optional: `voip` strips without one use its defaults (the `bridge` provider).
- A Mumble plugin (`integrations/mumble`, Mumble 1.4 and later) for `voip` strips: the people of your channel, who
  talks and how loud, the fader for their volume (the plugin's own, on top of Mumble's local volume) and Mute for
  Mumble's local mute (shown in Mumble; a local mute set in Mumble lights the button). "Install Mumble plugin" on the GUI's page "Voice chat" (or `xtouch-daemon mumble-plugin --install`)
  hands it to Mumble's installer, building it first in a checkout; the page lists the steps and tells whether Mumble
  is connected. Releases ship the plugin in `/usr/share/xtouch-daemon/`, CI builds it.
- The live view takes a request to switch the layout (`{"request": "layout", "layout": "gaming"}`, answered with a
  reply), and the state tells the layout shown.
- GUI: copy a strip (Ctrl+C or its context menu) and paste it in the place of another one (Ctrl+V), also of
  another layout; in a [[layout]] it asks whether to inherit it (an `inherit` strip) or copy all its options.
- The GUI edits layouts: a tab per layout above the strips (● marks the one the device shows), + adds one (empty or a
  copy), a "Layout" tab for its name, label and rules, the pages "Layouts" and "Voice chat" in the global settings,
  and "Show on the device". The strips are live only for the layout the device shows. `person` of a `voip` strip
  suggests the people in the voice chat now; the preview prints "voip group" or the person under a `voip` strip, and
  the strip list says who is on which strip.
- The live view tells the names of the voice chat's participants and who is on which strip.
- `just screenshot` renders the screenshots of the README and the documentation (docs/images/) offscreen, with a
  demo configuration and device, so they can be updated with the GUI.
- "Live preview" in the GUI: while it is on, the device runs the configuration in the editor before it is saved
  and follows every change. Saving keeps it; turning it off, closing the window, or a window that crashed or hangs
  brings back the file, and so does a change of the file on disk or a reload. Errors of the daemon show inline, and
  Home Assistant entities of strips the preview does not have stay as they are. It covers the layouts too
  ("Show on the device" switches to the one being edited). It needs a daemon of this version (restart an older
  one), which takes previews only from its own user.

- `lit_when_idle` on audio strips: the LCD keeps its backlight while the strip has nothing to control, e.g. an
  `apps` group whose applications don't play.
- Changing the type of a strip in the GUI loses no options: the ones the new type does not have are kept in the
  file as a comment in the strip's table, which the daemon ignores, and switching back restores them, also after
  saving and closing the GUI.
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
- A handle between the strips and the editor of the GUI: dragging it scales the strips, and the size is kept.
  The strips keep pictures of themselves, so they draw about ten times faster while it is dragged, also while
  the live view moves their meters and faders; they are drawn sharp once it is let go.
- "Stop" in the header of the GUI while the service runs: stops it, but leaves it enabled.
- The strips of the GUI look like the device: the ring has 13 LEDs, the LCD is a negative display (the backlight
  shines around a dark panel and through its characters and the line between its two lines), the meter has 8 LEDs next to the buttons (REC, SOLO and MUTE square, SELECT wider), whose names are printed under them,
  and the faders are longer, with the dB scale of the device: the middle of the cap marks the value, -∞ at the
  bottom, 0 dB at 77 % of the travel and +10 dB at the top.
  The meter lights its LEDs for a level as the device does (7 for the loudest audio, the red CLIP LED when it clips).
- GUI zoom, 67..300 %: Ctrl++ / Ctrl+= larger, Ctrl+- smaller, Ctrl+0 100 %, and a button in the header. It scales
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
  `[[layout]]` (the first setting of a layout for its strips) and per strip; the strip wins over the layout, the
  layout over `[behavior]`. The monitor of an output is before its volume (so its pre-fader meter is what it was
  before, and post-fader multiplies by the volume); streams and inputs apply their volume and Mute in their own
  PipeWire node, so their pre-fader level is the captured one divided by the volume, and a muted stream or input
  stays dark either way. On `voip` strips the Mumble plugin tells the level before and after the participant's
  volume; a muted participant who talks lights the meter before the fader (Mumble doesn't fetch their voice). The
  GUI shows it next to `meter`, on the layout page and on the behavior page; `check-config` names post-fader meters.
- A documentation site (Zensical, published to GitHub Pages): getting started, a page per topic of the
  configuration, Home Assistant, the GUI, every command, troubleshooting, hardware and architecture.

[0.1.0]: https://github.com/markusressel/xtouch-daemon/releases/tag/v0.1.0

### Fixed

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
