# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

- Strip types `output` and `input` (a device, or the default one; Select makes it the default), `apps` (all streams of
  a group of applications), `auto` (the next application that plays) and `empty`.
- Motor faders that glide smoothly (also after a connect, from the bottom), follow changes made elsewhere, stay still
  while touched, and get their value again after arriving so the motor doesn't stop short.
- LCD labels, volume and state on a backlight in the strip's color; Mute LED; encoder for fine steps, push to reset.
- Passive LED meters from `pw-record` captures.
- Strip type `homeassistant`: the fader, encoder, LCD lines and color, LEDs and button events of a strip become
  Home Assistant entities over MQTT discovery (`[mqtt]` section), for automations.
- Rec and Solo LEDs as configurable indicators (`rec`, `solo`): recording, playing, default, muted. By default Rec is
  lit while an application records the device, or while the applications of the strip record.
- Reconnects to the device and the sound server.
- systemd user service with `Type=notify`, reload on SIGHUP, journal log levels, and a dark surface on shutdown.
- Commands `run`, `check-config`, `init-config`, `list-devices`, `list-apps`, `test` and `install-service`.

[0.1.0]: https://github.com/markusressel/xtouch-daemon/releases/tag/v0.1.0
