# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

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
  The strips keep pictures of themselves, so they draw about ten times faster while it is dragged.
- "Stop" in the header of the GUI while the service runs: stops it, but leaves it enabled.
- The strips of the GUI look like the device: the ring has 13 LEDs, the LCD the lit line between its two lines, the
  meter 8 LEDs next to the buttons (REC, SOLO and MUTE square, SELECT wider), whose names are printed under them,
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
  place and the others make room (Escape cancels); strips also move with Ctrl+arrows and their context menu. Every edit
  can be undone (Ctrl+Z), also removing a strip and reverting the file.
- A clip indicator: when the audio of a strip peaks at full scale, its meter lights all 8 LEDs, the red one at the
  top too, for half a second. Below that, the meter uses 7 LEDs. The `homeassistant` meter entity reaches the red LED
  at 100 %.
- A documentation site (Zensical, published to GitHub Pages): getting started, a page per topic of the
  configuration, Home Assistant, the GUI, every command, troubleshooting, hardware and architecture.

[0.1.0]: https://github.com/markusressel/xtouch-daemon/releases/tag/v0.1.0

### Fixed

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
