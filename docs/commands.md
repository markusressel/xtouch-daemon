# Commands

| Command | What it does |
|---|---|
| [`xtouch-daemon run`](#run) | Runs the daemon in the foreground. |
| [`xtouch-daemon check-config`](#check-config) | Validates the configuration and lists what each strip does. |
| [`xtouch-daemon init-config`](#init-config) | Writes the example configuration. |
| [`xtouch-daemon list-devices`](#list-devices) | Lists outputs, inputs and the profiles of the sound cards. |
| [`xtouch-daemon list-apps`](#list-apps) | Lists the applications that play, and which strip takes each one. |
| [`xtouch-daemon test`](#test) | Tests the LCDs, LEDs, rings, meters and faders, then shows what happens on the device. |
| [`xtouch-daemon layout`](#layout) | Shows the running daemon's layout, or switches to another one. |
| [`xtouch-daemon mumble-plugin`](#mumble-plugin) | Shows, builds or installs the Mumble plugin of `voip` strips. |
| [`xtouch-daemon install-service`](#install-service) | Sets the daemon up as a systemd user service. |
| [`xtouch-daemon gui`](#gui) | Edits the configuration in a window. |

Every command takes `-h`/`--help`. `xtouch-daemon -V` (`--version`) shows the version.

`-c FILE` (`--config FILE`) selects the configuration file; the default is `~/.config/xtouch-daemon/config.toml`.

## `run`

```shell
xtouch-daemon run [-c FILE] [-l LEVEL]
```

Runs the daemon in the foreground. `install-service` sets it up as a systemd user service instead.

| Option | Meaning |
|---|---|
| `-c`, `--config FILE` | The configuration file. |
| `-l`, `--log-level LEVEL` | `debug`, `info` (default), `warning` or `error`. `debug` also logs the messages of the device the daemon doesn't use. |

The daemon notes its process and configuration file in `$XDG_RUNTIME_DIR/xtouch-daemon.json` while it runs, and
serves what the device shows on `$XDG_RUNTIME_DIR/xtouch-daemon.sock` for the [GUI](gui.md). A second daemon does not
start: it names the one that runs.

Signals:

| Signal | Effect |
|---|---|
| `SIGHUP` | Reloads the configuration (`systemctl --user reload xtouch-daemon`). A file with errors is logged, and the current configuration stays. |
| `SIGTERM`, `SIGINT` | Stops: the strips go dark from the right and the faders go down. |

## `check-config`

```shell
xtouch-daemon check-config [-c FILE]
```

Validates the configuration and shows what each strip does. Without a file at the default path it checks the
defaults. Example output:

```
/home/me/.config/xtouch-daemon/config.toml: valid
  1. 'Speaker' output alsa_output.pci-0000_11_00.4.analog-stereo, select makes it the default (cyan, rec: recording, solo: off)
  2. 'Mic' the default input (red, rec: recording, solo: off)
  3. 'Browser' applications brave, firefox (yellow, rec: recording, solo: off)
  4. 'Living' Home Assistant, entities *.*_living_room_* (yellow)
  5. empty
  6. the next application that plays (white, rec: recording, solo: off)
  ...
```

A file with errors names the place of each one, e.g. `strip[3].label: String should have at most 7 characters`, and
the command fails.

## `init-config`

```shell
xtouch-daemon init-config [PATH] [-f]
```

Writes the example configuration to `~/.config/xtouch-daemon/config.toml`, or to `PATH`. An existing file stays,
unless `-f` (`--force`) overwrites it.

## `list-devices`

```shell
xtouch-daemon list-devices
```

Lists the outputs and inputs with the node names to use as `device`, their descriptions, volumes and states; `*`
marks the defaults. Then it lists the profiles of each sound card, for [`profiles`](configuration/devices.md#profiles);
`*` marks the active ones.

## `list-apps`

```shell
xtouch-daemon list-apps [-c FILE]
```

Lists the applications that play now: their names (and aliases), binaries and volumes, and which strip takes each
one: an `apps` strip, an `auto` strip, "ignored" (`behavior.ignore`) or no strip. Use the names and binaries for
`match`, `ignore` and `[aliases]`.

## `test`

```shell
xtouch-daemon test [-c FILE] [--no-events]
```

Lights up everything on the device and moves the faders: every strip lights its LCD in a color, its LEDs, ring and
meter, and moves its fader up and down. Then it shows what you do on the device (faders, touches, buttons, encoders),
and the messages from the device the daemon doesn't use, until Ctrl+C. `--no-events` ends after the test.

It takes the name of the device from `[device]` of the configuration. Stop the daemon first
(`systemctl --user stop xtouch-daemon`): only one program can use the device.

## `layout`

```shell
xtouch-daemon layout [NAME | --next | --previous]
```

Without arguments it prints the [layouts](configuration/layouts.md) of the running daemon and marks the one the
device shows:

```
  default
* gaming
  music
```

`layout gaming` switches to the layout `gaming`, `--next` and `--previous` to the one after or before it, in the
order of the file (after the last one comes `default`). The choice stays until a [rule](configuration/layouts.md#rules)
starts or stops matching. A layout chosen by hand also comes back after a restart of the daemon (see
[Switching](configuration/layouts.md#switching)). It talks to the daemon over its live view socket, so it needs a
running daemon; the command fails when there is none, or no layout of that name.

## `mumble-plugin`

```shell
xtouch-daemon mumble-plugin [--build] [--install]
```

The [Mumble plugin](integrations/mumble.md) that gives `voip` strips the people of your Mumble channel. Without
options it tells where the plugin is, whether Mumble is installed, and whether Mumble has the plugin:

```
Plugin: /usr/share/xtouch-daemon/xtouch-daemon.mumble_plugin
Mumble: installed
In Mumble: /home/me/.local/share/Mumble/Mumble/Plugins/libxtouch-daemon.so
```

| Option | Meaning |
|---|---|
| `--install` | Opens the plugin with Mumble, which asks whether to install it (`mumble -m <plugin>`). Without a plugin it builds one first. |
| `--build` | Builds the plugin from the sources of a checkout (`integrations/mumble`, needs `cmake` and a C compiler) into `integrations/mumble/build/`. With `--install`: builds it again first. |

A release has the plugin in `/usr/share/xtouch-daemon/`; a checkout builds it.

## `install-service`

```shell
xtouch-daemon install-service [--now] [--remove-override]
```

Writes the systemd user unit `~/.config/systemd/user/xtouch-daemon.service` for the installed `xtouch-daemon` and
reloads systemd. `--now` also enables and starts it. The unit is `Type=notify`, reloads with `SIGHUP` and restarts
on failure.

The [Arch Linux package](getting-started.md#arch-linux) installs its unit as
`/usr/lib/systemd/user/xtouch-daemon.service`. Its `xtouch-daemon install-service` writes no file then: it reloads
systemd, and with `--now` enables and starts that unit. A unit in `~/.config/systemd/user` overrides the one of the
package (systemd prefers it), e.g. one written before by a checkout; the command says so.

| Option | Meaning |
|---|---|
| `--now` | Also enable and start the service. |
| `--remove-override` | Only remove `~/.config/systemd/user/xtouch-daemon.service`, so the unit of the package is in effect. An enabled service stays enabled, and a running one restarts with the program of the package. |

Logs: `journalctl --user -u xtouch-daemon -f`.

## `gui`

```shell
xtouch-daemon gui [-c FILE]
```

Edits the configuration in a window, and applies it. Needs the `gui` extra, or the package `xtouch-daemon-gui-bin`
(which has the command `xtouch-daemon-gui`). See [GUI](gui.md).
