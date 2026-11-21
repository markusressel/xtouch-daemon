# Install

## Arch Linux

The AUR has two packages. They repackage the releases on GitHub:

| Package | Contents |
|---|---|
| `xtouch-daemon-bin` | The daemon with its own Python 3.14, the command `xtouch-daemon`, the systemd user unit and an example configuration. |
| `xtouch-daemon-gui-bin` | The [GUI](../guides/gui.md), `xtouch-daemon-gui`, with a menu entry. It needs `xtouch-daemon-bin` of the same version. |

Install them with an AUR helper, e.g.:

```shell
paru -S xtouch-daemon-bin xtouch-daemon-gui-bin
```

Then enable the service as [First steps](first-steps.md#run-it-as-a-service) shows. After an upgrade, restart it
(`systemctl --user restart xtouch-daemon`): it runs the old version until then.

## From the source

xtouch-daemon needs the library [haad-mqtt-autodiscovery](https://github.com/haad-org/haad-mqtt-autodiscovery) (it
speaks MQTT for Home Assistant). The project expects its source in a folder next to its own, even if you never use Home Assistant. Clone both side by side and install with [uv](https://docs.astral.sh/uv/):

```shell
git clone https://github.com/markusressel/xtouch-daemon
git clone https://github.com/haad-org/haad-mqtt-autodiscovery
uv tool install ./xtouch-daemon
```

uv installs Python 3.14 if needed. The command `xtouch-daemon` is then in `~/.local/bin`; if your shell does not find
it, run `uv tool update-shell`. To upgrade, pull both repositories and run `uv tool install --force` again.

The [GUI](../guides/gui.md) is the optional `gui` extra, which brings Qt along. Install it instead of the command
above:

```shell
uv tool install --force './xtouch-daemon[gui]'
```

## The GUI

Start the [GUI](../guides/gui.md) from the menu of your desktop (the entry is called "X-Touch Extender"), or in a
terminal. The command is `xtouch-daemon-gui` for the Arch package and `xtouch-daemon gui` for the source install:

```shell
xtouch-daemon-gui            # Arch package: the default configuration file
xtouch-daemon-gui -c FILE    # another one
xtouch-daemon gui -c FILE    # source install: the same, with -c after gui
```

Without the extra, `xtouch-daemon gui` says how to install it.

Next: [First steps](first-steps.md), then the [Setup tour](tour.md).
