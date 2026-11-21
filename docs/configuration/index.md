# Configuration

xtouch-daemon reads a TOML file, by default `~/.config/xtouch-daemon/config.toml` (`$XDG_CONFIG_HOME` is respected).
Every command takes `-c FILE` after its name (e.g. `xtouch-daemon check-config -c my.toml`) to use another file.

Start with the
[example configuration](https://github.com/markusressel/xtouch-daemon/blob/main/src/xtouch_daemon/config.example.toml)
that ships with the daemon. It puts the default input on slot 7, the default output on slot 8 and `auto` (the next
application that plays) on the other six. A slot without an entry is always `auto`. The
[complete example](#complete-example) at the end of this page is longer.

Without a file at the default path, the daemon runs with the example file, and the [GUI](../guides/gui.md) starts
with an empty file and writes it at the first save.

```shell
xtouch-daemon init-config      # writes the example file to the default path (-f overwrites)
xtouch-daemon check-config     # validates the file and shows what each slot shows when
xtouch-daemon list-devices     # the names of your outputs and inputs, for `device` of a channel
```

`check-config` needs no X-Touch; its output is described in [Commands](../reference/commands.md#check-config). To run
the daemon as a service and read its log, see [First steps](../getting-started/first-steps.md).

A configuration can start programs (the `launch` of a channel, `run` in
[`[controls]`](slots.md#controls-and-the-chord)), and the daemon runs them as you. So it refuses a file in which
another user could put a command: one that belongs to another user (root is fine), or that the group or others can
write, or that sits in a directory they can write. For a symbolic link (for example from a dotfile manager), it
checks the file the link points to, the directories of both, in the same way.

The error names the file and the fix, e.g. `chmod go-w ~/.config/xtouch-daemon/config.toml`. The file that
`[mqtt] password_file` names should be readable only by you; if others can read it, the daemon still starts but
writes a warning to the log.

Unknown options are errors, so a typo does not go unnoticed. `check-config` names the place of every error, e.g.
`channel.mic.label: String should have at most 7 characters`. The [GUI](../guides/gui.md) shows the same errors next
to the options.

## Editors and AI assistants

Every option is also published as a [JSON Schema](https://json-schema.org/), [config.schema.json](../config.schema.json).
A TOML language server, e.g. [Taplo](https://taplo.tamasfe.dev/) (Even Better TOML in VS Code) or
[Tombi](https://tombi-toml.github.io/tombi/), reads it: it completes the options, shows their help on hover and marks a
wrong option while you type. The example configuration starts with this line; add it to a file that has none (the
daemon ignores it, it is a comment):

```toml
#:schema https://markusressel.github.io/xtouch-daemon/latest/config.schema.json
```

The line follows the latest release. For another version, write the schema of the installed one next to the file and
point to that:

```shell
xtouch-daemon schema > ~/.config/xtouch-daemon/config.schema.json
```

```toml
#:schema ./config.schema.json
```

An AI assistant that edits the file finds the options and their help there too. The schema checks each option on its
own; `check-config` checks the rest, e.g. that a slot names a channel that exists.

## Sections

| Section | What it configures | Page |
|---|---|---|
| `[channel.<id>]` | What a strip can control: your headphones, a group of applications, a person, Home Assistant. | [Channels](channels/index.md) |
| `[slots]` | The candidates for each of the 8 strips, and when each shows. | [Channels, states and slots](slots.md#slots) |
| `[state.<id>]` | States and modes (in a call, gaming) that the slots ask about. | [States and modes](slots.md#states-and-modes) |
| `[controls]` | Actions of the buttons, fader or encoder of a slot. | [Controls](slots.md#controls-and-the-chord) |
| `[pool.apps]`, `[pool.auto]` | Which applications the pools `apps` and `auto` skip, how long a slot keeps one, and the color of their strips. | [Applications](channels/applications.md#apps-and-auto) |
| `[pool.people]`, `[voip]` | The people of the voice chat, and which strips they take. | [People](channels/people.md) |
| `[pool.devices]` | Outputs and inputs without a channel (a USB headset). | [Devices](channels/devices.md#devices-without-a-channel) |
| `[pool.<id>]` | A pool of your own, e.g. of all your headphones. | [Pools of channels](slots.md#pools-of-channels) |
| `[device]` | Which sound card is the X-Touch, and its startup and shutdown. | [Behavior](behavior.md#device) |
| `[behavior]` | Volume limit, encoder step, reset volume, meters. | [Behavior](behavior.md#behavior) |
| `[aliases]` | Names to show for applications on `auto` slots. | [Behavior](behavior.md#aliases) |
| `[switching]` | The chord (Solo buttons held together switch the modes) and the banner of a new mode. | [Controls](slots.md#controls-and-the-chord) |
| `[mqtt]` | The MQTT broker of Home Assistant. | [Home Assistant](../guides/home-assistant.md#mqtt) |

The channel types:

| `type` | What the channel controls | Page |
|---|---|---|
| `output`, `input` | An output (your headphones) or an input (your microphone), or the default one. | [Devices](channels/devices.md) |
| `apps` | All streams of a group of applications. | [Applications](channels/applications.md#apps-channels) |
| `person` | Someone of the voice chat. | [People](channels/people.md#strips-for-one-person) |
| `homeassistant` | Nothing by itself: its parts are entities in Home Assistant. | [Home Assistant](../guides/home-assistant.md) |

In a slot, `apps` is not the channel type `apps`: it is a built-in pool, as are `people`, `auto` and `devices` (see
[the same word, different things](../concepts.md#the-same-word-different-things) and
[Pools](slots.md#slots)). `-` is a dark strip ([Channels](channels/index.md#empty-slots)). Presets (the `@browsers`
in `match`) are on [Presets](presets.md).

## Applying changes

The daemon takes a saved file by itself, a moment after the file stopped changing. It needs no restart, and a strip
whose slot still shows the same thing stays as it is. A file with errors is reported in the log, and the daemon keeps
the configuration it has. To check a file first and load it by hand (a reload, SIGHUP, does the same as a change of
the file):

```shell
xtouch-daemon check-config && systemctl --user reload xtouch-daemon
```

One section needs a restart (`systemctl --user restart xtouch-daemon`): a changed `[mqtt]`. It blocks the whole
reload: until the restart, the daemon ignores every change in the file, not only the ones in `[mqtt]`. The log says
so. A changed `[device] name` or `virtual` needs no restart: the daemon connects to the other X-Touch.

The GUI applies a file when you save it: it reloads the running daemon, or offers a restart when one is needed, and
tells you whether the daemon took the file.

## Complete example

The `device` values are the names of one computer: replace them with the ones `xtouch-daemon list-devices` prints.
`mic` has no `device`, so it controls the default input. `@browsers`, `@games` and `@steam-games` are
[presets](presets.md). In `"buds if present"`, the buds show while they are connected, else the slot is dark.

```toml
[behavior]
max_volume = 130
encoder_step = 2

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[channel.out]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[channel.buds]
type = "output"
device = "bluez_output.4C_D7_3A_EA_02_76.1"
label = "Buds"
color = "green"

[channel.mic]
type = "input"
label = "Mic"
color = "red"

[channel.browser]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "yellow"

[channel.game]
type = "apps"
match = ["@games"]
label = "Game"
color = "magenta"

[pool.apps]
exclude = ["speech-dispatcher", "notification"]

[state.gaming]
mode = true
label = "Gaming"
processes = ["@steam-games"]

[slots]
1 = "out"
2 = ["buds if present", "-"]
3 = "mic"
4 = "browser"
5 = ["game if gaming", "-"]
# slots 6 to 8 have no entry, so each is "auto" (the example file sets slots 7 and 8, this file does not)
```
