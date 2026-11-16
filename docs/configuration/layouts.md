# Layouts

A layout is a set of strips the device can switch to, e.g. one for games that shows the game, the voice chat, the
microphone and the people in the voice chat. The strips at the top level of the file (`[[strip]]`) are the layout
`default`. More layouts are `[[layout]]` sections, each with its own `[[layout.strip]]` list:

```toml
[[strip]]
type = "output"
label = "Speaker"

[[strip]]
type = "input"
label = "Mic"

[[layout]]
name = "gaming"
label = "Gaming"
apps = ["steam_app_", ".exe"]   # while a game plays, see Rules

[[layout.strip]]
type = "apps"
label = "Game"
match = ["steam_app_", ".exe"]

[[layout.strip]]
type = "apps"
label = "VoIP"
match = ["mumble"]

[[layout.strip]]
type = "inherit"    # the Mic of the default layout

[[layout.strip]]
type = "voip"       # the people in the voice chat, strips 4 to 8
count = 5

[voip]
provider = "demo"
```

A file without `[[layout]]` works as before: it has the layout `default` only.

| Option | Default | Meaning |
|---|---|---|
| `name` | (required) | What Home Assistant and `xtouch-daemon layout` call it: lower case letters, digits and `_`. Not `default`. |
| `label` | the name | What the LCDs show when the layout comes, across the strips (at most 56 characters). |
| `apps`, `processes`, `priority` | none | When the daemon switches to it by itself, see [Rules](#rules). |

Each layout has up to 8 strips, as the top level; missing ones are `auto`. The strips of a layout have the same
types and options as the top-level ones, plus [`inherit`](#inherit-strips). `homeassistant` strips of all layouts
keep their entities in Home Assistant, so automations don't lose them while another layout is shown.

## Switching

The daemon starts with the layout it showed when it stopped, unless a rule had put it there: then with the one
shown before (by hand, or `default` once no rule matched). It keeps that in `~/.local/state/xtouch-daemon/layout`
(`$XDG_STATE_HOME`, if set). A layout that is not in the configuration anymore gives `default`, and the rules still
win: if one matches right after the start (a game that still runs), its layout comes as usual. Another one comes:

- by hand: `xtouch-daemon layout gaming`, `xtouch-daemon layout --next` (see [Commands](../commands.md#layout)),
  or "Show on the device" in the [GUI](../gui.md);
- from Home Assistant: the select entity `select.xtouch_layout` (see [Home Assistant](../home-assistant.md#layouts));
- on the device: holding the Solo buttons of strips 1 and 8 together switches to the next layout;
- by its [rules](#rules).

When a layout comes, the strips change at once, like after a reload, and the LCDs show its label for a moment.

| Option of `[switching]` | Default | Meaning |
|---|---|---|
| `chord` | `[1, 8]` | The strips (from 1 on the left) whose Solo buttons, held together, switch to the next layout. `[]` for no chord. Solo does nothing on audio strips; `homeassistant` strips still send the presses to Home Assistant. |
| `hold` | `10` | Seconds a layout stays after its rule stopped matching, e.g. while a game loads. |
| `banner` | `1.5` | Seconds the LCDs show the label of the layout that comes; `0` for none. |

## Rules

`apps` and `processes` make the daemon switch to a layout by itself:

- `apps`: while one of these applications has a stream (playing or paused). Parts of the names or binaries, ignoring
  case, like `match` of [`apps` strips](applications.md).
- `processes`: while a process of one of these names runs (parts of the name, ignoring case), e.g. `"mumble"` for
  the voice chat even while nobody talks.

If several layouts match, the one with the highest `priority` comes, then the first one in the file. When none
matches any more, the `default` layout comes back, after `hold` seconds.

Rules switch only when what they want changes: a layout chosen by hand or from Home Assistant stays until a rule
starts or stops matching.

## Inherit strips

```toml
[[layout.strip]]
type = "inherit"
```

The strip of the default layout at the same place, with all its options. Only in layouts.

## VoIP strips

```toml
[[layout.strip]]
type = "voip"
count = 5
```

The people in the voice chat, one per strip, from the provider of [`[voip]`](#voice-chat). Needs a `[voip]`
section.

| Option | Default | Meaning |
|---|---|---|
| `count` | `1` | How many strips the participants take, from this one to the right. |
| `color` | `"white"` | The backlight while a participant is there and does not talk. Dark without one. |
| `talking_color` | `"green"` | The backlight while the participant talks. |
| `meter` | `true` | Whether the LED meter shows the participant's voice. Without levels from the provider it lights while the participant talks. |
| `max_volume` | `100` | The volume of a participant with the fader at the top, 1..200 percent. |

The top line shows the name, the bottom line `muted`, the volume while the fader moves, or `talks`. The fader sets
the participant's volume and Mute mutes them for you, if the provider can. With more participants than strips, the
Select LED is on and Select shows the next ones (`pg 2/3`).

## Voice chat

`[voip]` says where the participants come from:

| Option | Default | Meaning |
|---|---|---|
| `provider` | `"bridge"` | `bridge`: a plugin of the voice chat client sends them (see below). `demo`: people who are not there and talk in turns, to try `voip` strips. |
| `participants` | `["Alice", "Bob", "Carol", "Dave", "Eve"]` | The names of the `demo` people. |

None of the voice chat clients tells another program the volume of each person, so the daemon can't read them from
PipeWire: they all come out of one stream. Mumble and TeamSpeak have plugins that can, and the bridge is what such a
plugin talks to.

### The bridge protocol

The daemon serves the Unix socket `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock` (mode 0600). A plugin connects and
sends its whole state on every change, one JSON object per line:

```json
{"client": "mumble", "capabilities": ["volume", "mute", "levels"],
 "participants": [{"id": "12", "name": "Alice", "talking": true, "muted": false, "volume": 100, "level": 0.4}]}
```

`id` and `name` are needed, the rest is optional. `volume` is 0..200 percent, `level` 0..1. `capabilities` says what
the plugin can do: `volume` (the faders set volumes), `mute` (Mute mutes), `levels` (it sends `level`). The daemon
sends commands back the same way:

```json
{"set_volume": {"id": "12", "volume": 80}}
{"set_muted": {"id": "12", "muted": true}}
```

One plugin at a time: a new connection replaces the one before. When the plugin goes, so do the participants.
