# xtouch-daemon

Use a Behringer X-Touch Extender as a hardware mixer for PipeWire on Linux: motor faders, LED meters and scribble
strips for your devices and applications.

```
 ┌Speaker┐┌ Buds  ┐┌  Mic  ┐┌BudsMic┐┌Browser┐┌ VoIP  ┐┌ Games ┐┌Spotify┐
 │  46%  ││  44%  ││  80%  ││  off  ││  60%  ││ idle  ││ idle  ││  72%  │
 └───────┘└───────┘└───────┘└───────┘└───────┘└───────┘└───────┘└───────┘
   output   output   input    input    apps     apps     apps     auto
```

## Features

- **Device strips** control an output or input, or whatever is the default. **Select** makes the device the default
  output or input, and its LED shows which one is.
- **Application strips** control all streams of a group of applications at once, e.g. every browser. A stream that
  starts later gets the strip's volume.
- **Auto strips** pick up the next application that plays and has no strip of its own. They keep it for a few seconds
  after it stops, so it does not jump between strips from track to track. Aliases give applications readable names.
- **Motor faders** glide to new values smoothly, follow changes made anywhere else, and stay still while your finger
  is on them.
- **Scribble strips** show a label and the volume (or `muted`, `idle`, `off`) on a backlight in the strip's color. A
  strip whose device or applications are not there goes dark.
- **Mute** button with LED. The **encoder** fine-tunes the volume, a push resets it (to 100 % by default).
- **LED meters** show the level of each strip. They are passive: they never wake a device, never light your
  desktop's microphone indicator, and never switch Bluetooth headphones into headset mode.
- **Robust:** survives unplugging or switching off the device and restarts of the sound server, and shows everything
  again when they are back.
- **A proper service:** systemd notification (`Type=notify`), `systemctl --user reload` applies a changed
  configuration without a restart, and the log goes to the journal with levels. When it stops, it leaves the surface
  dark.

## Requirements

- Linux with PipeWire and `pipewire-pulse` (or PulseAudio).
- `pw-record` (part of PipeWire) for the meters.
- Python 3.12 or newer.
- A Behringer X-Touch Extender in **MC** mode on **USB** (see [docs/hardware.md](docs/hardware.md)). Your user needs
  access to its MIDI device in `/dev/snd`, which desktop sessions grant to the logged-in user.

## Installation

With [uv](https://docs.astral.sh/uv/):

```shell
uv tool install git+https://github.com/markusressel/xtouch-daemon
```

Or with [pipx](https://pipx.pypa.io/):

```shell
pipx install git+https://github.com/markusressel/xtouch-daemon
```

## Quick start

```shell
xtouch-daemon test                    # lights up the device and moves the faders, then echoes what you do on it
xtouch-daemon init-config             # writes ~/.config/xtouch-daemon/config.toml
xtouch-daemon list-devices            # the names to use for device strips
xtouch-daemon list-apps               # the applications that play now, and which strip takes them
xtouch-daemon check-config            # validates the file and shows what each strip does
xtouch-daemon install-service --now   # runs it as a systemd user service from now on
```

Without a configuration file it uses the example configuration: six auto strips, the default input and the default
output.

## Configuration

A TOML file at `~/.config/xtouch-daemon/config.toml`. Up to eight `[[strip]]` sections, from the left:

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

After a change, check it and apply it:

```shell
xtouch-daemon check-config && systemctl --user reload xtouch-daemon
```

[docs/configuration.md](docs/configuration.md) describes every option and what each strip type does with the faders,
buttons and encoders.

## Commands

| Command | What it does |
|---|---|
| `xtouch-daemon run [-c FILE] [-l LEVEL]` | Runs the daemon in the foreground. |
| `xtouch-daemon check-config [-c FILE]` | Validates the configuration and lists what each strip does. |
| `xtouch-daemon init-config [PATH] [-f]` | Writes the example configuration. |
| `xtouch-daemon list-devices` | Lists outputs and inputs with their node names; `*` marks the defaults. |
| `xtouch-daemon list-apps [-c FILE]` | Lists the applications that play, and which strip takes each one. |
| `xtouch-daemon test [-c FILE] [--no-events]` | Tests the LCDs, LEDs, rings, meters and faders, then echoes events. |
| `xtouch-daemon install-service [--now]` | Writes the systemd user unit (and enables and starts it with `--now`). |

Logs: `journalctl --user -u xtouch-daemon -f`.

## Troubleshooting

**The device shows `IP: 192.168.001.100 wait...`.** It is set to its network interface and ignores USB. Switch it to
MC mode on USB in its setup menu, see [docs/hardware.md](docs/hardware.md#setting-up-the-device).

**`can't open X-Touch-Ext (... Device or resource busy)`.** Only one program can use the device. Stop the daemon
before `xtouch-daemon test` (`systemctl --user stop xtouch-daemon`), and close DAWs or other MIDI tools that opened it.

**The meters stay dark.** A meter shows a level only while something plays to the output or records from the input.
That is on purpose: the meters never open a device themselves. A microphone meter moves only while an application
records from it.

**Streams don't follow when I select another output.** Select makes the device the default, and streams without a
fixed target follow the default. A stream that another tool moved to a particular device (pavucontrol's per-stream
output menu, `pactl move-sink-input`) stays there. Move it back in pavucontrol, or restart the application's stream.

**A strip shows `off`.** The device it controls is not there, e.g. Bluetooth headphones that are switched off. It
comes back by itself.

## Similar projects

- [deej](https://github.com/omriharel/deej): sliders on an Arduino, sent over a serial port. Cheap and popular, but
  one-way: no motor faders, LEDs or displays.
- [x-touch-nobara-app-mixer](https://github.com/turkey415/x-touch-nobara-app-mixer): the same device and idea, as a
  single script. Select pins the focused window's application (KDE). Its meters use PulseAudio peak detection, which
  WirePlumber 0.5.18 restores at 0 % volume, so they can stay silent.
- [SlideWire](https://github.com/NilsBriggen/SlideWire): a GUI mixer for generic MIDI controllers, with motor fader and
  LED support, but no Mackie Control displays.
- [apptrol](https://github.com/Dzobash/apptrol): per-application volume for the Korg nanoKONTROL2.

## Documentation

- [Configuration](docs/configuration.md)
- [Hardware and protocol](docs/hardware.md)
- [Architecture](docs/architecture.md)
- [Contributing](CONTRIBUTING.md)

## License

[AGPL-3.0-or-later](LICENSE)
