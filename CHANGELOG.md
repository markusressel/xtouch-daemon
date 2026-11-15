# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

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
  turning seeks 5 s per step, a push plays or pauses, the ring shows how far the track is.
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
- A documentation site (Zensical, published to GitHub Pages): getting started, a page per topic of the
  configuration, Home Assistant, the GUI, every command, troubleshooting, hardware and architecture.

[0.1.0]: https://github.com/markusressel/xtouch-daemon/releases/tag/v0.1.0

### Fixed

- After the device was switched off and on again, the faders stayed at the bottom: they come up to their values
  again.
- The meter of an output that was the default followed the default to the next output after Select (WirePlumber
  makes such a capture follow the default); meters now stay with their device.
- A balance a hair off the center lit only the center LED of the ring, like an exact center.
- Volumes above 153 % (`max_volume` up to 200) ended at 153 %: pulsectl limits volumes to where the sliders of
  pavucontrol end.
