# Commands

| Command | What it does |
|---|---|
| [`xtouch-daemon run`](#run) | Runs the daemon in the foreground. |
| [`xtouch-daemon check-config`](#check-config) | Validates the configuration, describes its channels and shows what the slots show when. |
| [`xtouch-daemon init-config`](#init-config) | Writes the example configuration. |
| [`xtouch-daemon schema`](#schema) | Prints the JSON Schema of the configuration, for editors. |
| [`xtouch-daemon list-devices`](#list-devices) | Lists outputs, inputs, and the sound cards with their profiles. |
| [`xtouch-daemon list-apps`](#list-apps) | Lists the applications that play, and which channel or slot takes each one. |
| [`xtouch-daemon test`](#test) | Tests the LCDs, LEDs, rings, meters and faders, then shows what happens on the device. |
| [`xtouch-daemon virtual-device`](#virtual-device) | Runs a virtual X-Touch Extender, for trying the daemon without the device. |
| [`xtouch-daemon mode`](#mode) | Shows the running daemon's mode, or picks another one. |
| [`xtouch-daemon why`](#why) | Says why a slot shows what it shows, or where a channel is and why. |
| [`xtouch-daemon mumble-plugin`](#mumble-plugin) | Shows, builds or installs the Mumble plugin for the strips of people. |
| [`xtouch-daemon teamspeak-plugin`](#teamspeak-plugin) | Shows, builds or installs the TeamSpeak plugin for the strips of people. |
| [`xtouch-daemon install-service`](#install-service) | Sets the daemon up as a systemd user service. |
| [`xtouch-daemon gui`](#gui) | Edits the configuration in a window. |
| [`xtouch-daemon simulate`](#simulate) | What the slots of a configuration show in a situation you give it. |
| [`xtouch-daemon observe`](#observe) | Records what plays, records and runs, for `simulate --replay`. |

Every command takes `-h`/`--help`. `xtouch-daemon -V` (`--version`) shows the version.

`-c FILE` (`--config FILE`) selects the configuration file; the default is `~/.config/xtouch-daemon/config.toml`.
Write it after the command name (`xtouch-daemon check-config -c FILE`). Only the commands that read the configuration
take it: `run`, `check-config`, `list-apps`, `test` and `gui`. (`simulate` and `init-config` take the file as an
argument.)

As root, every command except `schema` and `simulate` fails with an error: the daemon and the tools around it run as
your user. (`schema` and `simulate` run no commands of a configuration and read no configuration of your user, so root may use
them.) A configuration file that other users can change (a file or directory that is writable by the group or by everyone) is
an error too, see [Configuration](../configuration/index.md).

## `run`

```shell
xtouch-daemon run [-c FILE] [-l LEVEL] [--virtual-device]
```

Runs the daemon in the foreground. `install-service` sets it up as a systemd user service instead.

| Option | Meaning |
|---|---|
| `-c`, `--config FILE` | The configuration file. |
| `-l`, `--log-level LEVEL` | `debug`, `info` (default), `warning` or `error`. `debug` also logs the MIDI messages of the device that the daemon has no use for. |
| `--virtual-device` | Drives the [virtual device](#virtual-device) instead of the real one, as `[device] virtual = true`. |

The daemon notes its process and configuration file in `$XDG_RUNTIME_DIR/xtouch-daemon.json` while it runs, and
serves what the device shows on `$XDG_RUNTIME_DIR/xtouch-daemon.sock` for the [GUI](../guides/gui.md). A second daemon does not
start: it prints the process of the daemon that already runs, and exits.

Signals:

| Signal | Effect |
|---|---|
| `SIGHUP` | Reloads the configuration (`systemctl --user reload xtouch-daemon`), as the daemon does by itself when the file changes. If the file has errors, the daemon logs them and keeps the current configuration. |
| `SIGTERM`, `SIGINT` | Stops: the strips go dark from the right and the faders go down. |

## `check-config`

```shell
xtouch-daemon check-config [-c FILE] [--all]
```

Validates the configuration, describes each channel and shows a table of what the slots show in which states.
Without a file at the default path it checks the built-in defaults of every option (not the example file). It needs no running daemon. Example output:

```
/home/me/.config/xtouch-daemon/config.toml: valid
Channels:
  out: 'Speaker' output alsa_output.pci-0000_11_00.4.analog-stereo, select makes it the default (cyan, rec: recording, solo: off, encoder: balance)
  mic: the default input (red, rec: recording, solo: off, encoder: balance)
  browser: 'Browser' applications @browsers (firefox, chromium, ...) (yellow, rec: recording, solo: off, encoder: media)
  lamp: 'Living' Home Assistant, entities *.*_lamp_* (yellow)
What the slots show:
when     1    2        3     4-8
default  out  browser  auto  auto
call     out  browser  mic   auto
```

The line of a channel says what it is: its label (`'Speaker'`), its kind (`output`, or `Home Assistant` for a
`homeassistant` channel, whose entities are `*.*_lamp_*`) and its sound device or applications. The brackets after it
say how it looks and what its controls do: the color of the LCD (`cyan`), what the LED
of Rec and Solo shows (`rec: recording` lights while an application records, `solo: off` never lights) and what the
encoder edits (`encoder: balance`, or `media` for the media player of an application). The table at the end has a row for each situation:
the first column (`when`) names the situation: `default` when no mode and no state is on, else the mode or the
state that is on (here `call`). The other columns are the slots 1 to 8 (equal neighbors are joined: `4-8`). A cell is what the slot
shows in that situation: a channel (`out`), or the pool `auto`.

A channel with [`choices`](../configuration/channels/devices.md#choices) lists them, e.g.
`output: Phones, Speaker or Buds (Select switches)`. A channel whose meter shows the level after its fader
(`meter_point = "post_fader"`, see [Meters](../configuration/channels/index.md#meters)) says `meter post-fader`.

For a [custom channel](../configuration/channels/custom.md) (a strip whose parts you bound to programs of your own)
the line names each part that has a binding and the shell command it runs. If the channel has `targets` (the things
it controls one at a time), a line per target follows with the commands as they run for that target, e.g.
`Left: fader.set sysctrl display redshift brightness -d DisplayPort-1 -b '{value}'`.

The table can have many rows: one for each combination of modes and states. With more than 12 rows, `check-config`
shows only the situations that differ from `default` in one thing (one mode, or one state turned on or off) and
says how many it left out. `--all` shows every combination.

A file with errors names the place of each one and its line in the file, e.g.
`channel.mic (line 12): label: String should have at most 7 characters`, with what is likely meant where it can be
guessed (`browsr is no channel or pool (did you mean browser?)`), and the command fails. After the table, `Notes:` lists candidates that can never show and people with no slot to sit on. An example of a
candidate that can never show is `["auto", "browser"]`: the pool `auto` always has something for the slot, so the
candidate `browser` below it never comes up.

## `init-config`

```shell
xtouch-daemon init-config [PATH] [-f]
```

Writes the example configuration with [channels, states and slots](../configuration/slots.md) to
`~/.config/xtouch-daemon/config.toml`, or to `PATH`. If the file exists already, the command fails and leaves it
alone; `-f` (`--force`) overwrites it.

## `schema`

```shell
xtouch-daemon schema > ~/.config/xtouch-daemon/config.schema.json
xtouch-daemon schema --bridge
```

Prints the [JSON Schema](../configuration/index.md#editors-and-ai-assistants) of the configuration of the installed
version. Editors with a TOML language server complete the options from it and show their help. `--bridge` prints the
schema of the [voice chat bridge](voice-chat-bridge.md) instead, for plugins of other voice chat clients.

## `list-devices`

```shell
xtouch-daemon list-devices [--snippet]
```

Lists the outputs and inputs with the node names to use as `device`, their descriptions, volumes and states; `*`
marks the defaults (the devices that the sound server uses when nothing else is set). Then it lists each sound card by its name and description, with its devices and its profiles
(name and description), for `card` and `profile` of [`choices`](../configuration/channels/devices.md#choices) and for
[`profiles`](../configuration/channels/devices.md#profiles); `*` marks the active ones. `--snippet` prints a
`[channel.<id>]` for each device instead, ready to paste into the file (Bluetooth devices by a wildcard like
`bluez_output.*`, since their names hold the address of the device):

```
Profiles of alsa_card.pci-0000_11_00.4, Family 17h/19h HD Audio Controller (alsa_output.pci-0000_11_00.4.analog-stereo):
  * output:analog-stereo+input:analog-stereo
      Analog Stereo Output + Analog Stereo Input
    output:iec958-stereo+input:analog-stereo
      Digital Stereo (IEC958) Output + Analog Stereo Input
```

## `list-apps`

```shell
xtouch-daemon list-apps [-c FILE]
```

Lists the applications that play now: their names (and aliases), the [presets](../configuration/presets.md) they are
part of (e.g. `Brave (@browsers)`), binaries and volumes, and where each one goes: the `apps` channel that has it,
an `auto` or `apps` slot, "ignored" (`exclude` of `[pool.apps]`) or no slot. Use the names and binaries, or the
presets, for `match`, `exclude` and `[aliases]`.

## `test`

```shell
xtouch-daemon test [-c FILE] [--no-events] [--virtual-device]
```

Lights up everything on the device and moves the faders: every strip lights its LCD in a color, its LEDs, ring and
meter, and moves its fader up and down. Then every strip answers its own controls, until Ctrl+C, so you can check each
LED, the ring, the colors, the motor and the touch of every fader:

| Input on a strip | What the strip shows |
|---|---|
| Fader moved | The meter follows the fader. |
| Fader touched, let go | `touch`, `let go` |
| Rec, Solo, Mute, Select pressed | Its [LED](../configuration/strip/leds.md) goes on, flashing, off (`mute on`, `mute fl`, `mute off`). |
| Encoder turned | Changes the value of the thing the [encoder](../configuration/strip/encoders.md) edits at that moment (wrapping around), and shows that value. |
| Encoder pushed | The next thing the encoder edits: the position of the ring (`ring 7`), its mode with and without the two LEDs at the ends of the ring (`dot`, `boost`, `wrap`, `spread`, `dot+c` ...), the color of the LCD, the motor fader in steps of 10 % (`fad 60%`). |

The top line of the LCD names the strip, the bottom line shows the last input for 2 seconds, then what the encoder
edits. The command prints every input with the answer, and the messages from the device the daemon doesn't use.
`--no-events` ends after the sweep.

While the daemon runs, it has the device, so `test` cannot open it. Instead `test` asks the daemon to run the test
(the GUI's "Test the device" does the same). The slots go on, but show on the device again only when the test ends;
the log of the daemon shows the inputs (`journalctl --user -u xtouch-daemon -f`). In this case the test runs until
Ctrl+C and the sweep alone is not possible: `--no-events` fails while the daemon runs. Stop the daemon first
for `--no-events`.

Without a daemon, `test` opens the device itself. It finds the sound card by the `name` in `[device]` of the
configuration. `--virtual-device` (or `[device] virtual = true`) tests the [virtual device](#virtual-device) instead;
that device has to run already, in another terminal.

## `virtual-device`

```shell
xtouch-daemon virtual-device [--broken-touch 1,4] [--log-level debug]
```

A virtual X-Touch Extender, for trying the daemon without the device: `xtouch-daemon run --virtual-device` (or
`[device] virtual = true`) drives it instead of the real one, and the GUI shows what it shows. It runs headless until
interrupted (Ctrl+C); the GUI can host one itself, with the mouse on its strips. One daemon at a time can use it.

| Option | Meaning |
|---|---|
| `--broken-touch` | The faders whose touch sensor failed, counted from 1 on the left, e.g. `1,4`: they never report a touch, see [Motor faders](hardware.md#motor-faders). |
| `--log-level` | `debug` also logs every message of the daemon. |

## `mode`

```shell
xtouch-daemon mode [NAME | auto | --next | --previous]
```

Without arguments it prints the [modes](../configuration/slots.md#states-and-modes) of the running daemon (a mode is
a state of which only one is on at a time), marks the one that is on, and says whether it was picked by hand.
`mode gaming` picks the mode `gaming`, `--next` and `--previous` pick the one after or before it, and the word
`auto` lets the rules decide again. (`auto` here is no mode name.) It talks to the running daemon over a socket, so it
needs the daemon.

## `why`

```shell
xtouch-daemon why SLOT | CHANNEL
```

Asks the running daemon why a slot (its number, 1 for the leftmost one) shows what it shows. It says which candidate
of the slot wins and why each candidate before it (higher in the entry of the slot) does not. For a channel (its id)
it tells on which slots the channel is and why it is not on the others that offer it:

```
$ xtouch-daemon why 2
Slot 2: voip if call: doesn't hold (call is off); shows auto:app:firefox
$ xtouch-daemon why browser
browser: on slot 4; not slot 8 (on slot 4 (tie, to the left))
```

The first example reads: the first candidate of slot 2, `voip if call`, does not hold because the state `call` is
off, so the slot shows the next one: `auto`, which gave it the application Firefox (`auto:app:firefox`). In the
second example, the channel `browser` is offered by slots 4 and 8, but a channel takes one strip only. The daemon
gives each slot a rank for the channel (how high it is in the list of that slot). Here both ranks are the same, a
"tie", and then the left slot wins. (The two examples come from different configurations.)

The GUI shows the same above the inspector of a slot on the page Slots.

## `mumble-plugin`

```shell
xtouch-daemon mumble-plugin [--build] [--install]
```

The [Mumble plugin](../guides/mumble.md) that gives the strips of people the people of your Mumble channel. Without
options it tells where the plugin is, whether Mumble is installed, and whether Mumble has the plugin:

```
Plugin: /usr/share/xtouch-daemon/xtouch-daemon.mumble_plugin
Mumble: installed
In Mumble: /home/me/.local/share/Mumble/Mumble/Plugins/libxtouch-daemon.so
```

| Option | Meaning |
|---|---|
| `--install` | Copies the plugin into Mumble's plugin directory (native, else the Flatpak's), replacing an older one; then Mumble needs "Reload plugins". Without a plugin it builds one first. |
| `--build` | Builds the plugin from the sources in a git clone of the project (`integrations/mumble`, needs `cmake` and a C compiler; a release has the plugin built already) into `integrations/mumble/build/`. With `--install`: builds it again first. |

A release has the plugin in `/usr/share/xtouch-daemon/`; a checkout (a git clone of the source) builds it.

## `teamspeak-plugin`

```shell
xtouch-daemon teamspeak-plugin [--build] [--install]
```

The [TeamSpeak plugin](../guides/teamspeak.md) that gives the strips of people the people of your TeamSpeak channel.
Without options it tells where the plugin is, whether TeamSpeak 3 is installed, and whether TeamSpeak has the plugin:

```
Plugin: /usr/share/xtouch-daemon/xtouch-daemon_linux_amd64.so
TeamSpeak: installed
In TeamSpeak: /home/me/.ts3client/plugins/xtouch-daemon_linux_amd64.so
```

| Option | Meaning |
|---|---|
| `--install` | Copies the plugin into `~/.ts3client/plugins`, replacing an older one; then TeamSpeak needs "Reload All" (Tools, Options, Addons) or a restart. Without a plugin it builds one first. |
| `--build` | Builds the plugin from the sources in a git clone of the project (`integrations/teamspeak`, needs `cmake` and a C compiler; a release has the plugin built already) into `integrations/teamspeak/build/`. The first build downloads the headers of TeamSpeak's plugin SDK into `integrations/teamspeak/sdk/`. With `--install`: builds it again first. |

A release has the plugin in `/usr/share/xtouch-daemon/`; a checkout builds it. TeamSpeak counts as installed with
a `teamspeak3` command, `/opt/teamspeak3` or `~/.ts3client`.

## `install-service`

```shell
xtouch-daemon install-service [--now] [--remove-override]
```

Writes the systemd user unit `~/.config/systemd/user/xtouch-daemon.service` for the installed `xtouch-daemon` and
reloads systemd. `--now` also enables and starts it. The unit is `Type=notify`, reloads with `SIGHUP` and restarts
on failure.

The [Arch Linux package](../getting-started/install.md#arch-linux) installs its unit as
`/usr/lib/systemd/user/xtouch-daemon.service`. Its `xtouch-daemon install-service` writes no file then: it reloads
systemd, and with `--now` enables and starts that unit. A unit in `~/.config/systemd/user` overrides the one of the
package (systemd prefers it), e.g. one written before by a checkout; the command says so.

| Option | Meaning |
|---|---|
| `--now` | Also enable and start the service. |
| `--remove-override` | Only remove `~/.config/systemd/user/xtouch-daemon.service`, so the unit of the package is in effect (an "override" here is the unit file in your home directory that takes the place of the package's unit). An enabled service stays enabled, and a running one restarts with the program of the package. |

Logs: `journalctl --user -u xtouch-daemon -f`.

## `gui`

```shell
xtouch-daemon gui [-c FILE]
```

Edits the configuration in a window, and applies it. It needs the optional part `gui` of the package (the "extra"; install it with
`uv tool install --force './xtouch-daemon[gui]'`; the command does not run without it), or on Arch Linux the package
`xtouch-daemon-gui-bin` (which has the command `xtouch-daemon-gui`). See [GUI](../guides/gui.md) and
[Install](../getting-started/install.md).

## `simulate`

```shell
xtouch-daemon simulate FILE [--mode NAME] [--state NAME]... [--absent CHANNEL]... [--playing APP]... [--person NAME]... [--table | --replay LOG]
```

Shows what the 8 slots of FILE show in the situation you give, and why not the candidates before the one shown (see
[Channels, states and slots](../configuration/slots.md)).

| Option | Meaning |
|---|---|
| `--mode`, `--state` | The mode and the states that are on; the others are off. |
| `--absent` | A channel that is not present; the others are. |
| `--playing`, `--person` | The applications that play (in the order they started) and the people in the voice chat, for the pools `auto` and `people`. |
| `--table` | Instead of one situation, a table like that of `check-config`: a row for each combination of states and absent channels that changes what the slots show. |
| `--replay LOG` | Instead: replays observations recorded by `observe` through FILE. Prints when states and slots changed, how often each slot changed, the flaps (a slot back to what it showed within 60 s) and how long each state was on. |

## `observe`

```shell
xtouch-daemon observe LOG [--interval 2.0] [--process NAME]...
```

Records, every `--interval` seconds, what plays and records on the sound server, the devices, the running processes
(those of the presets, and `--process`) and the voice chat of the running daemon, and appends a line of JSON to LOG
when that changed. The field `absent` of a line lists the channels that are not there now: a channel can say when it is present
(for a [`custom` channel](../configuration/channels/custom.md), its option `present`). It runs until you interrupt it (Ctrl+C); a line is written only when something changed, so a quiet machine
makes a small file. `simulate FILE --replay LOG` replays the log.
