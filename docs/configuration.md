# Configuration

xtouch-daemon reads a TOML file, by default `~/.config/xtouch-daemon/config.toml` (`$XDG_CONFIG_HOME` is respected).
`-c FILE` selects another one. Without a file at the default path it uses the
[example configuration](../src/xtouch_daemon/config.example.toml): six `auto` strips, the default input and the
default output.

```shell
xtouch-daemon init-config      # writes the example to the default path (-f overwrites)
xtouch-daemon check-config     # validates the file and lists what each strip does
```

Unknown options are errors, so a typo does not go unnoticed. `check-config` names the place of every error, e.g.
`strip[3].label: String should have at most 7 characters`.

## Applying changes

```shell
xtouch-daemon check-config && systemctl --user reload xtouch-daemon
```

A reload (SIGHUP) builds the strips from the new file without a restart. A file with errors is reported in the log
and the current configuration stays. A changed `[device]` section needs a restart
(`systemctl --user restart xtouch-daemon`).

## `[device]`

| Option | Default | Meaning |
|---|---|---|
| `name` | `"X-Touch-Ext"` | Part of the name of the extender's sound card, as `/proc/asound/cards` lists it. |

## `[behavior]`

| Option | Default | Meaning |
|---|---|---|
| `max_volume` | `100` | The volume of a fader at the top, 100..150 percent. Above 100 % the audio is amplified in software. |
| `encoder_step` | `1` | Percent per encoder step, 1..10. |
| `reset_volume` | `100` | The volume a push on an encoder sets, 0..150, at most `max_volume`. |
| `meters` | `true` | Whether the LED meters show audio levels at all. |
| `auto_hold` | `5` | Seconds an `auto` strip keeps an application after it stopped playing. |
| `ignore` | `["speech-dispatcher"]` | Applications `auto` strips never take: parts of the name or binary, ignoring case. |

## `[aliases]`

The name to show on an `auto` strip for an application, at most 7 characters:

```toml
[aliases]
"WEBRTC VoiceEngine" = "Discord"
"Firefox" = "Firefox"
```

The key is the application name the sound server reports. `xtouch-daemon list-apps` shows it.

## `[[strip]]`

Up to eight, from the left. Strips that are not configured are `auto` strips.

Options of every strip type except `empty`:

| Option | Default | Meaning |
|---|---|---|
| `color` | `"white"` | The LCD backlight: `off`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`. |
| `meter` | `true` | Whether this strip's LED meter shows the level (if `behavior.meters` is on). |
| `rec` | `"recording"` | What the LED of the Rec button shows, see below. |
| `solo` | `"off"` | What the LED of the Solo button shows, see below. |

Labels are at most 7 characters of ASCII: that is what fits on the LCD.

The Rec and Solo LEDs are indicators; their buttons do nothing. Each shows one of:

| Indicator | Lit while |
|---|---|
| `recording` | An application records: from the input, from the monitor of the output (e.g. a screen recorder), or for `apps`/`auto` strips, the application records anything (e.g. Discord using a microphone). Level meters don't count: the daemon's own, pavucontrol's. |
| `playing` | Audio flows: the device runs, or a stream of the applications plays. |
| `default` | The device is the default output/input. Never for applications. |
| `muted` | The strip is muted (like the Mute LED). |
| `off` | Never. |

```toml
[[strip]]
type = "input"
label = "Mic"
rec = "recording"   # the default: lit while an application uses the microphone
solo = "default"
```

### `type = "output"` / `type = "input"`

A device: an output (a sink) or an input (a source).

| Option | Default | Meaning |
|---|---|---|
| `device` | the default device | The node name (`xtouch-daemon list-devices`) or the description of the device. Without it, the strip follows whatever device is the default. |
| `label` | `"Output"` / `"Input"`, or the start of the device's description | The top line of the LCD. |
| `select` | `true` | Whether Select makes the device the default. Needs `device`. |

```toml
[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[[strip]]
type = "input"          # the default input
label = "Mic"
color = "red"
```

| Element | Function |
|---|---|
| Fader | Sets the volume, 0 at the bottom to `max_volume` at the top. Follows changes made elsewhere. |
| Encoder | Changes the volume by `encoder_step` per step; the fader follows. |
| Encoder push | Sets `reset_volume`. |
| Mute | Toggles mute. The LED is on while the device is muted. |
| Select | With `device` and `select`: makes the device the default output/input. The LED is on while it is the default. |
| LCD | Top: the label. Bottom: the volume, or `muted`. |
| Ring | The volume. |
| Meter | The level: what plays on an output, what an input records. |

A device that is not there (e.g. Bluetooth headphones that are switched off) shows `off` on a dark LCD. Its fader goes
down, and the fader and buttons do nothing until it is back.

Use the node name for a device that is both an output and an input under one description, e.g. Bluetooth headphones
with a microphone. A description matches only devices of the strip's direction, but a node name is unambiguous and
stays the same across restarts.

### `type = "apps"`

All playback streams of a group of applications.

| Option | Default | Meaning |
|---|---|---|
| `match` | required | Parts of application names or binaries, ignoring case. |
| `label` | required | The top line of the LCD. |

```toml
[[strip]]
type = "apps"
match = ["discord", "webrtc", "teamspeak", "mumble"]
label = "VoIP"
color = "white"
```

A stream belongs to the strip when its application name (`application.name`) or binary
(`application.process.binary`) contains one of the `match` entries. `"wine"` matches `wine64-preloader`, `".exe"`
matches Windows games under Proton. `xtouch-daemon list-apps` shows the names and binaries of the applications that
play, and which strip takes each one. A stream can belong to several `apps` strips.

| Element | Function |
|---|---|
| Fader | Sets every stream of the group to the same volume. A stream that starts later gets that volume too. Shows the loudest stream. |
| Encoder | Changes the volume by `encoder_step` per step. |
| Encoder push | Sets `reset_volume` for all streams. |
| Mute | Mutes all streams, or unmutes them when all are muted. The LED is on while all are muted. |
| Select | Nothing. |
| LCD | Top: the label. Bottom: the volume, `muted`, or `idle` while no stream of the group is there. |
| Ring | The volume. |
| Meter | The level of all streams of the group together. |

While no stream of the group is there, the LCD is dark and shows `idle`. The fader still works: it sets the volume the
next stream gets.

The strip changes the volume of the streams themselves, like the per-application sliders in pavucontrol, so it needs
no setup in PipeWire.

### `type = "auto"`

The next application that plays and has no strip of its own.

```toml
[[strip]]
type = "auto"
color = "cyan"
```

How `auto` strips get their applications:

- An application qualifies while at least one of its streams plays (is not paused).
- Applications that an `apps` strip matches, and applications in `behavior.ignore`, never go to `auto` strips.
- Free `auto` strips take new applications from the left, in the order the applications started.
- An application keeps its strip while it plays, and for `behavior.auto_hold` seconds after it stopped. Then the strip
  is free again. This way a music player does not jump to another strip between two tracks.
- The label is the application's alias from `[aliases]`, or its name.
- A newly assigned application keeps its own volume.

An `auto` strip works like an `apps` strip for its application. Without an application it is dark, blank, and does
nothing.

### `type = "empty"`

A dark strip that does nothing. Its fader stays at the bottom. It has no options besides `type`.

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
