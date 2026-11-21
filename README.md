<p align="center"><img src="src/xtouch_daemon/gui/qt/theme/images/icon.svg" width="128" alt="The icon of xtouch-daemon: four strips of the device"></p>

# xtouch-daemon

Use a Behringer X-Touch Extender as a hardware mixer for PipeWire on Linux: motor faders, LED meters and scribble
strips for your devices, applications and the people in your voice chat. What each strip shows follows what you do:
a game, a call, headphones plugged in. Strips can also belong to Home Assistant, for lights, other speakers or scenes.

![The GUI: the device as it is, the slots and the inspector of the slot picked](docs/images/gui.png)

**Documentation: <https://markusressel.github.io/xtouch-daemon/>** (also readable in [docs/](docs/index.md)).

## Features

The device has 8 strips. Each has a slot in the configuration: a list of what the strip can show, top first, and
**states** (in a call, gaming) decide which entry wins now. See [Concepts](docs/concepts.md).

- **Devices, applications, people, Home Assistant.** A strip controls an output or input (with Select switching
  between several), all streams of a group of applications (presets for browsers, games, voice chats, ...), one
  person of your Mumble or TeamSpeak channel, or entities for your Home Assistant automations.
- **Programs of your own.** Any part of a strip can be bound to Home Assistant or to a program, e.g. a fader that
  sets the brightness of two screens (`set` with the value, `watch` for changes). See
  [Bindings](docs/configuration/strip/bindings.md) and [Custom channels](docs/configuration/channels/custom.md).
- **Pools** fill slots with whatever is there: the next application that plays, the next person of the voice chat,
  an output without a channel.
- **Modes** (gaming, work, ...) by rules or by hand: the chord (two Solo buttons together), `xtouch-daemon mode`, or
  Home Assistant.
- **The whole device:** motor faders that glide and stay still while touched, LCDs, encoders, LED rings and meters
  that never wake a device.
- **A GUI** (`xtouch-daemon gui`) with the device live, Simulate, and a virtual device when you have none.
- **A systemd user service** that recovers from an unplugged device or a restarted sound server, and explains itself
  (`check-config`, `why`, `simulate`).

See the [documentation](docs/index.md) for the rest.

## Installation

On Arch Linux, from the AUR: `xtouch-daemon-bin` (the daemon, with its own Python, and the systemd user unit) and
`xtouch-daemon-gui-bin` (the GUI, on the system's PyQt6):

```shell
paru -S xtouch-daemon-bin xtouch-daemon-gui-bin
systemctl --user enable --now xtouch-daemon
```

From the source: xtouch-daemon uses [haad-mqtt-autodiscovery](https://github.com/haad-org/haad-mqtt-autodiscovery)
from a checkout next to its own, so clone both side by side and install with [uv](https://docs.astral.sh/uv/):

```shell
git clone https://github.com/markusressel/xtouch-daemon
git clone https://github.com/haad-org/haad-mqtt-autodiscovery
uv tool install ./xtouch-daemon          # or './xtouch-daemon[gui]' for the GUI
```

The device has to be in **MC** mode on **USB**, see [Getting started](docs/getting-started/first-steps.md#set-up-the-device). No
device yet? `xtouch-daemon run --virtual-device`, or "Try without a device" in the GUI, see
[Without a device](docs/getting-started/without-a-device.md).

## Quick start

```shell
xtouch-daemon test                    # lights up the device and moves the faders, then echoes what you do on it
xtouch-daemon init-config             # writes ~/.config/xtouch-daemon/config.toml
xtouch-daemon gui                     # edit it in a window, with the device live (or by hand, see below)
xtouch-daemon list-devices            # the names to use for output and input channels
xtouch-daemon check-config            # validates the file and shows what each slot shows when
xtouch-daemon install-service --now   # runs it as a systemd user service from now on
```

A configuration names channels, states, and what each slot shows when:

```toml
[channel.buds]
type = "output"
device = "bluez_output.*"     # any Bluetooth headphones
label = "Buds"
color = "green"

[channel.game]
type = "apps"
match = ["@steam-games"]      # a preset: Steam games, Proton and Wine
label = "Game"
color = "red"

[state.gaming]
mode = true                   # one mode at a time
label = "Gaming"              # the banner across the LCDs
processes = ["@steam-games"]

[slots]
1 = ["buds if present", "auto"]
2 = ["game if gaming", "auto"]
# slots 3 to 8 have no entry: "auto", the next application or person without a slot
```

## Documentation

- [Getting started](docs/getting-started/install.md)
- [Concepts](docs/concepts.md)
- [Configuration](docs/configuration/index.md): [channels, states and slots](docs/configuration/slots.md),
  [devices](docs/configuration/channels/devices.md), [applications](docs/configuration/channels/applications.md),
  [people](docs/configuration/channels/people.md)
- [Home Assistant](docs/guides/home-assistant.md)
- [Mumble](docs/guides/mumble.md)
- [TeamSpeak](docs/guides/teamspeak.md)
- [GUI](docs/guides/gui.md)
- [Commands](docs/reference/commands.md)
- [Troubleshooting](docs/guides/troubleshooting.md)
- [Hardware and protocol](docs/reference/hardware.md)
- [Architecture](docs/development/architecture/index.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Releasing](RELEASING.md)

## Similar projects

- [deej](https://github.com/omriharel/deej): sliders on an Arduino, sent over a serial port. Cheap and popular, but
  one-way: no motor faders, LEDs or displays.
- [x-touch-nobara-app-mixer](https://github.com/turkey415/x-touch-nobara-app-mixer): the same device and idea, as a
  single script. Select pins the focused window's application (KDE). Its meters use PulseAudio peak detection, which
  WirePlumber 0.5.18 restores at 0 % volume, so they can stay silent.
- [SlideWire](https://github.com/NilsBriggen/SlideWire): a GUI mixer for generic MIDI controllers, with motor fader and
  LED support, but no Mackie Control displays.
- [apptrol](https://github.com/Dzobash/apptrol): per-application volume for the Korg nanoKONTROL2.
- [BehringerXTouchExtender](https://github.com/Aldaviva/BehringerXTouchExtender): a .NET library for this device in
  its MIDI (`Ctrl`, `CtrlRel`) and HUI modes, not Mackie Control. Its documentation of the hardware (13 ring LEDs, 8
  meter LEDs and their colors, the LCD message of MIDI mode with inverted text, the firmware that AMD Zen 2 and later
  need for a stable USB connection) helped here.

## License

[AGPL-3.0-or-later](LICENSE)
