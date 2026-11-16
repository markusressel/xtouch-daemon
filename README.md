# xtouch-daemon

Use a Behringer X-Touch Extender as a hardware mixer for PipeWire on Linux: motor faders, LED meters and scribble
strips for your devices and applications. Strips can also belong to Home Assistant, for lights, other speakers or
scenes.

![The GUI: the eight strips as the device shows them, and the options of the selected one](docs/images/gui.png)

**Documentation: <https://markusressel.github.io/xtouch-daemon/>** (also readable in [docs/](docs/index.md)).

## Features

- Strips for outputs and inputs (one, several, or the default), groups of applications, and the next application
  that plays.
- Motor faders that glide, follow changes made elsewhere and stay still while touched.
- LCDs with label, volume and color, Mute, encoders for balance, volume, picking the application or the media player, passive LED
  meters, Rec and Solo LEDs as indicators.
- Sound card profiles on Rec, volume ranges up to 200 %.
- Home Assistant strips over MQTT discovery, or just the encoder or fader of an audio strip.
- A Qt GUI with a live view of the device and a live preview of unsaved changes, a systemd user service with reload.

See the [full feature list](docs/index.md#features).

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

The device has to be in **MC** mode on **USB**, see [Getting started](docs/getting-started.md#set-up-the-device).

## Quick start

```shell
xtouch-daemon test                    # lights up the device and moves the faders, then echoes what you do on it
xtouch-daemon init-config             # writes ~/.config/xtouch-daemon/config.toml
xtouch-daemon list-devices            # the names to use for device strips
xtouch-daemon list-apps               # the applications that play now, and which strip takes them
xtouch-daemon check-config            # validates the file and shows what each strip does
xtouch-daemon install-service --now   # runs it as a systemd user service from now on
```

A configuration has up to eight strips, from the left:

```toml
[[strip]]
type = "output"
device = "bluez_output.4C_D7_3A_EA_02_76.1"
label = "Buds"
color = "green"

[[strip]]
type = "apps"
match = ["discord", "teamspeak", "mumble"]
label = "VoIP"
color = "white"

[[strip]]
type = "auto"
color = "cyan"
```

## Documentation

- [Getting started](docs/getting-started.md)
- [Configuration](docs/configuration/index.md)
- [Home Assistant](docs/home-assistant.md)
- [GUI](docs/gui.md)
- [Commands](docs/commands.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Hardware and protocol](docs/hardware.md)
- [Architecture](docs/architecture.md)
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
