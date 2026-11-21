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

Then enable the service as [First steps](first-steps.md#run-it-as-a-service) shows. After an upgrade, restart the service (`systemctl --user restart xtouch-daemon`): the service runs the
old version until then.

## From the source

xtouch-daemon needs the library [haad-mqtt-autodiscovery](https://github.com/haad-org/haad-mqtt-autodiscovery) (it
speaks MQTT for Home Assistant). The project expects its source in a folder next to its own, even if you never use Home Assistant. Clone both side by side and install with [uv](https://docs.astral.sh/uv/):

```shell
git clone https://github.com/markusressel/xtouch-daemon
git clone https://github.com/haad-org/haad-mqtt-autodiscovery
uv tool install ./xtouch-daemon
```

uv installs Python 3.14 if your system does not have it. The command `xtouch-daemon` is then in `~/.local/bin`. If
your shell does not find it, run `uv tool update-shell` and open a new terminal. To upgrade, pull both repositories and
run the `uv tool install` command again with `--force`.

The [GUI](../guides/gui.md) is an optional part, the `gui` extra. Instead of the command above, install it with the
extra (`--force` replaces the install you already have). The extra brings Qt along:

```shell
uv tool install --force './xtouch-daemon[gui]'
```

## The GUI

The [GUI](../guides/gui.md) comes with `xtouch-daemon-gui-bin` (Arch Linux) or the `gui` extra (from the source), see
above. Start it from the menu of your desktop (the entry is called "X-Touch Extender"), or in a terminal. The command
is `xtouch-daemon-gui` for the Arch package and `xtouch-daemon gui` for the source install:

```shell
xtouch-daemon-gui            # the default configuration file
xtouch-daemon-gui -c FILE    # another one
```

Without the extra, `xtouch-daemon gui` says how to install it.

Next: [First steps](first-steps.md), then the [Setup tour](tour.md).
