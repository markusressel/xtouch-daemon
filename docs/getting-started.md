# Getting started

## Install

### Arch Linux

The AUR has two packages, built from the [releases](https://github.com/markusressel/xtouch-daemon/releases):

| Package | Contents |
|---|---|
| `xtouch-daemon-bin` | The daemon with its own Python 3.14 in `/usr/lib/xtouch-daemon`, the command `xtouch-daemon`, the systemd user unit `/usr/lib/systemd/user/xtouch-daemon.service` and the example configuration `/usr/share/xtouch-daemon/config.example.toml`. |
| `xtouch-daemon-gui-bin` | The [GUI](gui.md), `xtouch-daemon-gui`, with a menu entry. It runs on the system's Python and PyQt6, and needs `xtouch-daemon-bin` of the same version. |

Install them with an AUR helper, e.g.:

```shell
paru -S xtouch-daemon-bin xtouch-daemon-gui-bin
```

Then enable the service, see [Run it as a service](#run-it-as-a-service). After an upgrade, restart it
(`systemctl --user restart xtouch-daemon`): it runs the old version until then.

### From the source

xtouch-daemon uses [haad-mqtt-autodiscovery](https://github.com/haad-org/haad-mqtt-autodiscovery) from a checkout
next to its own. Clone both side by side and install with [uv](https://docs.astral.sh/uv/):

```shell
git clone https://github.com/markusressel/xtouch-daemon
git clone https://github.com/haad-org/haad-mqtt-autodiscovery
uv tool install ./xtouch-daemon
```

uv installs Python 3.14 if your system does not have it. The command `xtouch-daemon` is then on your `PATH`.

For the [GUI](gui.md), install the `gui` extra instead. It brings Qt along, so it needs no system packages:

```shell
uv tool install --force './xtouch-daemon[gui]'
```

## Set up the device

The extender has to be in **MC** (Mackie Control) mode on **USB**. Out of the box it may be set to the network
interface: then it shows `IP: 192.168.001.100 wait...` and ignores USB.

1. Switch it off.
2. Hold the **Select** button of strip 1 and switch it on: the setup menu opens.
3. Set **Mode** to `MC` and **Interface** to `USB` with the encoders.
4. Leave the menu (Select of strip 1 again, or switch it off and on).

Connect it over USB. It needs no driver. Your user needs access to its MIDI device in `/dev/snd`: desktop sessions
grant it to the logged-in user. Without a session, add the user to the `audio` group. See
[Hardware](hardware.md#linux-access) for details.

## Test the device

```shell
xtouch-daemon test
```

Every strip lights its LCD in a color, its LEDs, ring and meter, and moves its fader. Afterwards the command shows what
you do on the device: faders, buttons and encoders. Ctrl+C stops it.

Only one program can use the device. Stop the daemon before the test (`systemctl --user stop xtouch-daemon`), and close
DAWs that use it.

## Write a configuration

Without a configuration file the daemon uses the example configuration: six `auto` strips, the default input and the
default output. To change it, write the example to `~/.config/xtouch-daemon/config.toml` and edit it:

```shell
xtouch-daemon init-config     # writes ~/.config/xtouch-daemon/config.toml
xtouch-daemon list-devices    # the names to use for device strips, and the profiles of the sound cards
xtouch-daemon list-apps       # the applications that play now, and which strip takes them
xtouch-daemon check-config    # validates the file and shows what each strip does
```

`init-config` writes the format of [channels, states and slots](configuration/slots.md), which replaces the strips
and layouts below; `init-config --strips` writes the example with strips, which the GUI edits for now, and
`migrate-config` turns such a file into the new format.

Up to eight `[[strip]]` sections, from the left. For example:

```toml
[[strip]]
type = "output"
device = "bluez_output.4C_D7_3A_EA_02_76.1"
label = "Buds"
color = "green"

[[strip]]
type = "apps"
match = ["@voip"]   # Discord, Mumble, TeamSpeak and more, see Presets
label = "VoIP"
color = "white"

[[strip]]
type = "auto"
color = "cyan"
```

Strips that are not configured are `auto` strips. [Configuration](configuration/index.md) describes every option.
`xtouch-daemon gui` edits the same file in a window, see [GUI](gui.md).

## Run it as a service

```shell
xtouch-daemon install-service --now
```

This writes the systemd user unit `~/.config/systemd/user/xtouch-daemon.service`, enables it and starts it. From now on
it starts with your session. Without `--now` it only writes the unit.

The Arch Linux package has its own unit, so with it the command writes nothing: it enables and starts the unit of the
package. The same without the command:

```shell
systemctl --user enable --now xtouch-daemon
```

A unit in `~/.config/systemd/user` (e.g. from an installation from the source) overrides the one of the package.
`xtouch-daemon install-service --remove-override` removes it, so does "Use the packaged unit" in the [GUI](gui.md#the-service).

| Task | Command |
|---|---|
| Apply a changed configuration | `xtouch-daemon check-config && systemctl --user reload xtouch-daemon` |
| Restart (after changing `[device] name` or `[mqtt]`) | `systemctl --user restart xtouch-daemon` |
| Stop (e.g. for `xtouch-daemon test`) | `systemctl --user stop xtouch-daemon` |
| See whether the device, sound server and broker are connected | `systemctl --user status xtouch-daemon` |
| Follow the log | `journalctl --user -u xtouch-daemon -f` |

To run it in the foreground instead, e.g. to watch the log while you try something:

```shell
xtouch-daemon run -l debug
```
