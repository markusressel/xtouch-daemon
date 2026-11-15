# Configuration

xtouch-daemon reads a TOML file, by default `~/.config/xtouch-daemon/config.toml` (`$XDG_CONFIG_HOME` is respected).
`-c FILE` selects another one. Without a file at the default path it uses the
[example configuration](https://github.com/markusressel/xtouch-daemon/blob/main/src/xtouch_daemon/config.example.toml):
six `auto` strips, the default input and the default output.

```shell
xtouch-daemon init-config      # writes the example to the default path (-f overwrites)
xtouch-daemon check-config     # validates the file and lists what each strip does
```

Unknown options are errors, so a typo does not go unnoticed. `check-config` names the place of every error, e.g.
`strip[3].label: String should have at most 7 characters`.

The [GUI](../gui.md) edits the same options in a window and shows the same errors next to them.

## Sections

| Section | What it configures | Page |
|---|---|---|
| `[device]` | Which sound card is the extender. | [Behavior](behavior.md#device) |
| `[behavior]` | Volume limit, encoder step, reset volume, meters, `auto` strips. | [Behavior](behavior.md#behavior) |
| `[aliases]` | Names to show for applications on `auto` strips. | [Behavior](behavior.md#aliases) |
| `[[strip]]` | Up to eight strips, from the left. | [Strips](strips.md) |
| `[mqtt]` | The MQTT broker of Home Assistant. | [Home Assistant](../home-assistant.md#mqtt) |

The strip types:

| `type` | What the strip controls | Page |
|---|---|---|
| `output`, `input` | An output or an input device, several of them, or the default one. | [Devices](devices.md) |
| `apps` | All streams of a group of applications. | [Applications](applications.md#apps-strips) |
| `auto` | The next application that plays and has no strip of its own. | [Applications](applications.md#auto-strips) |
| `homeassistant` | Nothing by itself: its parts are entities in Home Assistant. | [Home Assistant](../home-assistant.md) |
| `empty` | Nothing. A dark strip. | [Strips](strips.md#empty-strips) |

## Applying changes

```shell
xtouch-daemon check-config && systemctl --user reload xtouch-daemon
```

A reload (SIGHUP) builds the strips from the new file without a restart. A file with errors is reported in the log
and the current configuration stays.

Two sections need a restart (`systemctl --user restart xtouch-daemon`):

- A changed `[device]` section. A reload takes the rest of the file, but keeps the old device.
- A changed `[mqtt]` section. Until the restart, a reload keeps the whole current configuration.

The GUI applies a saved file the same way: it reloads the running daemon (the service, or one started from a terminal
or an IDE), or offers a restart. It then tells whether the daemon took the file.

## Complete example

```toml
[behavior]
max_volume = 100
encoder_step = 2
auto_hold = 10
ignore = ["speech-dispatcher", "notification"]

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[[strip]]
type = "output"
device = "bluez_output.4C_D7_3A_EA_02_76.1"
label = "Buds"
color = "green"

[[strip]]
type = "input"
label = "Mic"
color = "red"

[[strip]]
type = "apps"
match = ["brave", "firefox"]
label = "Browser"
color = "yellow"

[[strip]]
type = "apps"
match = ["steam", "wine", "proton", ".exe"]
label = "Games"
color = "magenta"

[[strip]]
type = "empty"

# strips 7 and 8 are not configured: they are "auto" strips
```
