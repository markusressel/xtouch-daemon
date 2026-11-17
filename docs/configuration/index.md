# Configuration

xtouch-daemon reads a TOML file, by default `~/.config/xtouch-daemon/config.toml` (`$XDG_CONFIG_HOME` is respected).
`-c FILE` selects another one. Without a file at the default path it uses the
[example configuration](https://github.com/markusressel/xtouch-daemon/blob/main/src/xtouch_daemon/slots.example.toml):
six `auto` slots, the default input and the default output.

```shell
xtouch-daemon init-config      # writes the example to the default path (-f overwrites)
xtouch-daemon check-config     # validates the file and shows what each slot shows when
```

Unknown options are errors, so a typo does not go unnoticed. `check-config` names the place of every error, e.g.
`channel.mic.label: String should have at most 7 characters`. A file with strips and layouts, the format before,
fails with a pointer to [`migrate-config`](slots.md#migrating).

The [GUI](../gui.md) edits the same options in a window and shows the same errors next to them.

## Sections

| Section | What it configures | Page |
|---|---|---|
| `[channel.<id>]` | What a strip can control: a device, a group of applications, a person, Home Assistant. | [Channels](strips.md) |
| `[slots]` | What each strip of the device (a slot) shows, and when. | [Channels, states and slots](slots.md#slots) |
| `[state.<id>]` | States and modes (in a call, gaming) that the slots ask about. | [Channels, states and slots](slots.md#states-and-modes) |
| `[controls]` | Actions of the buttons, fader or encoder of a slot, whatever it shows. | [Channels, states and slots](slots.md#controls-and-the-chord) |
| `[pool.auto]` | How `auto` takes the next application that plays. | [Applications](applications.md#auto) |
| `[people]`, `[voip]` | The people of the voice chat. | [People](people.md) |
| `[device]` | Which sound card is the extender. | [Behavior](behavior.md#device) |
| `[behavior]` | Volume limit, encoder step, reset volume, meters. | [Behavior](behavior.md#behavior) |
| `[aliases]` | Names to show for applications on `auto` slots. | [Behavior](behavior.md#aliases) |
| `[switching]` | The chord and the banner of a new mode. | [Channels, states and slots](slots.md#controls-and-the-chord) |
| `[mqtt]` | The MQTT broker of Home Assistant. | [Home Assistant](../home-assistant.md#mqtt) |

The channel types:

| `type` | What the channel controls | Page |
|---|---|---|
| `output`, `input` | An output or an input device, several of them, [choices](devices.md#choices) to switch between, or the default one. | [Devices](devices.md) |
| `apps` | All streams of a group of applications. | [Applications](applications.md#apps-channels) |
| `person` | Someone of the voice chat. | [People](people.md#strips-for-one-person) |
| `homeassistant` | Nothing by itself: its parts are entities in Home Assistant. | [Home Assistant](../home-assistant.md) |

In a slot, `auto` is the next application that plays and has no channel of its own ([Applications](applications.md#auto)),
`-` a dark strip ([Channels](strips.md#empty-slots)).

## Applying changes

```shell
xtouch-daemon check-config && systemctl --user reload xtouch-daemon
```

A reload (SIGHUP) takes the new file without a restart: slots whose strip stays the same keep it. A file with errors is reported in the log
and the current configuration stays.

Two sections need a restart (`systemctl --user restart xtouch-daemon`):

- A changed `[device] name`. A reload takes the rest of the file, but keeps the old device.
- A changed `[mqtt]` section. Until the restart, a reload keeps the whole current configuration.

The GUI applies a saved file the same way: it reloads the running daemon (the service, or one started from a terminal
or an IDE), or offers a restart. It then tells whether the daemon took the file.

## Complete example

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

[pool.auto]
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
# slots 6 to 8 have no entry: they are "auto"
```
