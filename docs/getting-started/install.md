# Install

## Arch Linux

The AUR has two packages, built from the [releases](https://github.com/markusressel/xtouch-daemon/releases):

| Package | Contents |
|---|---|
| `xtouch-daemon-bin` | The daemon with its own Python 3.14 in `/usr/lib/xtouch-daemon`, the command `xtouch-daemon`, the systemd user unit `/usr/lib/systemd/user/xtouch-daemon.service` and the example configuration `/usr/share/xtouch-daemon/config.example.toml`. |
| `xtouch-daemon-gui-bin` | The [GUI](../guides/gui.md), `xtouch-daemon-gui`, with a menu entry. It runs on the system's Python and PyQt6, and needs `xtouch-daemon-bin` of the same version. |

Install them with an AUR helper, e.g.:

```shell
paru -S xtouch-daemon-bin xtouch-daemon-gui-bin
```

Then enable the service, see [Run it as a service](first-steps.md#run-it-as-a-service). After an upgrade, restart it
(`systemctl --user restart xtouch-daemon`): it runs the old version until then.

## From the source

xtouch-daemon uses [haad-mqtt-autodiscovery](https://github.com/haad-org/haad-mqtt-autodiscovery) from a checkout
next to its own. Clone both side by side and install with [uv](https://docs.astral.sh/uv/):

```shell
git clone https://github.com/markusressel/xtouch-daemon
git clone https://github.com/haad-org/haad-mqtt-autodiscovery
uv tool install ./xtouch-daemon
```

uv installs Python 3.14 if your system does not have it. The command `xtouch-daemon` is then on your `PATH`.

For the [GUI](../guides/gui.md), install the `gui` extra instead. It brings Qt along, so it needs no system packages:

```shell
uv tool install --force './xtouch-daemon[gui]'
```

## The GUI

The [GUI](../guides/gui.md) comes with `xtouch-daemon-gui-bin` (Arch Linux) or the `gui` extra (from the source), see
above. It starts with `xtouch-daemon-gui` (the package, also "X-Touch Extender" in the menu of the desktop) or
`xtouch-daemon gui` (from the source):

```shell
xtouch-daemon-gui            # the default configuration file
xtouch-daemon-gui -c FILE    # another one
```

Without the extra, `xtouch-daemon gui` says how to install it.

Next: [First steps](first-steps.md).
