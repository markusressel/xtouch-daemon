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
type = "voip"       # always Bob
person = "Bob"

[[layout.strip]]    # strips 5 to 8: the others in the voice chat
type = "voip"
[[layout.strip]]
type = "voip"
[[layout.strip]]
type = "voip"
[[layout.strip]]
type = "voip"

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

The strip of the default layout at the same place, with all its options. Without `layout` or `strip`, only in
layouts.

| Option | Default | Meaning |
|---|---|---|
| `layout` | the default layout | The `name` of the layout of the strip. |
| `strip` | the strip at this place | The strip in that layout: its position in the layout's list (from 1), or its `id`. |

```toml
[[layout]]
name = "games"

[[layout.strip]]
type = "inherit"
layout = "voice"
strip = 3          # the third strip of the layout voice

[[layout.strip]]
type = "inherit"
strip = "music"    # the strip with id = "music" of the default layout
```

The strip comes with all its options: `collapse` (it collapses here too), `launch`, its volume range. An inherited
`voip` strip is one of the `voip` strips of this layout: with `person` it shows that person here too, without it it
joins the group of this layout. An `inherit` strip may refer to another one (up to 8 in a row); strips that refer to
each other in a loop are an error that names them. `check-config` tells where each inherited strip comes from.

A `homeassistant` strip (or one with `fader` or `encoder` in Home Assistant) keeps the entities of its own place,
`strip_<position there>` without an `id`, so the same entities show it in every layout. Two strips with the same
entities in one layout are an error.

A strip shared by layouts is built again when the layout switches, like every strip: an `auto` strip takes the
application that plays at the time, and a choice that Select is still switching to is dropped (its card may be in
the new profile already; Select again finishes it).

## VoIP strips

```toml
[[layout.strip]]
type = "voip"
person = "Alice"    # always Alice

[[layout.strip]]
type = "voip"       # the group: whoever else is there
[[layout.strip]]
type = "voip"
```

A `voip` strip is a person in the voice chat, from the provider of [`[voip]`](#voice-chat). Without a `[voip]`
section, the strips use its defaults: the `bridge` provider, which the Mumble plugin feeds. Each `voip` strip is one
strip; for five people, write five.

| Option | Default | Meaning |
|---|---|---|
| `person` | none: the group | The person the strip always shows: a name, or a list of names of the same person, see [Strips for one person](#strips-for-one-person). |
| `label` | the first name of `person` | The top line of a strip with `person`. |
| `color` | `"white"` | The backlight while a participant is there and does not talk. Dark without one. |
| `talking_color` | `"green"` | The backlight while the participant talks. |
| `meter` | `true` | Whether the LED meter shows the participant's voice. Without levels from the provider it lights while the participant talks. |
| `max_volume` | `behavior.max_volume` | The volume of a participant with the fader at the top, 1..200 percent; 100 % is at the 0 dB mark as on the other strips. Above 100 % the voice is louder than Mumble plays it, and may clip. |
| `collapse` | `false` | Whether the strip gives its fader to the strips after it while it shows nobody, see [Collapsing strips](collapsing.md). |
| `launch` | none | A command that Select starts while the voice chat is not there, e.g. `["mumble", "mumble://markus@voice.example.org/Gaming"]`, see [Launching the application](applications.md#launching-the-application). |

The top line shows the name, the bottom line `muted`, the volume while the fader moves, or `talks`. The fader sets
the participant's volume and Mute mutes them for you, if the provider can. The daemon remembers the volume and the
mute it set for each name while it runs, and sets them again when that person comes back (the voice chat starts
them at 100 % otherwise).

With `launch`, Select starts the voice chat while its plugin does not report and its program does not run; the
Select LED flashes while it starts. The `voip` strips of a layout with the same command start it once, whichever of
them is pressed. `launch_when_running` is not for `voip` strips: while the voice chat is there, Select pages.

`count` is gone: a file with `count = 5` gets the error
``count is gone: write N voip strips; voip strips without `person` form a group``. Write five `voip` strips instead.

### The group

The `voip` strips of a layout without `person` are its group, in the order of the file, also when other strips are
between them. They show the people in the voice chat who have no strip of their own, in the order the provider tells
them (for Mumble: who came first).

- More people than strips of the group: the Select LED of the group's strips is on, and Select on any of them shows
  the next ones (`pg 2/3`), after the last page the first again.
- Fewer: the strips left over are dark. With `collapse = true` they give their faders to the strips after them.

### Strips for one person

```toml
[[layout.strip]]
type = "voip"
person = ["Alice", "alice-phone"]   # the same person, from the desk or the phone
label = "Mum"
collapse = true
```

With `person`, the strip always shows that person. The names are the names in the voice chat, ignoring case, but
otherwise exactly (no wildcards, no parts of a name). With several names, the first person of the provider's order
with one of them is on the strip; someone with another of the names (Alice on two devices) goes to the group.

While the person is not in the channel, the strip shows the name dark, `away` on the second line and its fader at
the bottom; with `collapse = true` it gives its fader to the strips after it instead. The volume and mute the strip
set stay with the name while they are away and come back with them.

A name may be on one strip of a layout only: two strips for the same person are an error
(`voip strips with the same person: alice`). The person's strip takes them out of the group, so the group shows the
others.

## Voice chat

`[voip]` says where the participants come from:

| Option | Default | Meaning |
|---|---|---|
| `provider` | `"bridge"` | `bridge`: a plugin of the voice chat client sends them (see below). `demo`: people who are not there and talk in turns, to try `voip` strips. |
| `participants` | `["Alice", "Bob", "Carol", "Dave", "Eve"]` | The names of the `demo` people. |

None of the voice chat clients tells another program the volume of each person, so the daemon can't read them from
PipeWire: they all come out of one stream. Mumble and TeamSpeak have plugins that can, and the bridge is what such a
plugin talks to. For Mumble there is one: see [Mumble](../integrations/mumble.md), which the GUI installs with a click.

### The bridge protocol

The daemon serves the Unix socket `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock` (mode 0600). When a plugin connects,
the daemon says who it is and which version of the protocol it speaks:

```json
{"daemon": "xtouch-daemon", "version": "0.1.0", "protocol": 1}
```

The plugin sends its whole state on every change (and while someone talks, for the levels, e.g. 20 times a second),
one JSON object per line:

```json
{"protocol": 1, "client": "mumble", "channel": "Lobby", "capabilities": ["volume", "mute", "levels"],
 "participants": [{"id": "12", "name": "Alice", "talking": true, "muted": false, "volume": 100, "level": 0.4}]}
```

`id` and `name` are needed, the rest is optional; without `protocol` it is 1. `channel` is the channel the user is
in (the GUI shows it). `volume` is 0..200 percent, `level` 0..1. `capabilities` says what
the plugin can do: `volume` (the faders set volumes), `mute` (Mute mutes), `levels` (it sends `level`). The daemon
sends commands back the same way:

```json
{"set_volume": {"id": "12", "volume": 80}}
{"set_muted": {"id": "12", "muted": true}}
```

One plugin at a time: a new connection replaces the one before. When the plugin goes, so do the participants.

**Versions.** Both sides ignore keys they don't know, so new optional keys keep the version. A change that an older
side would get wrong gets a new `protocol` number; the daemon ignores (and logs) the lines of a protocol it does not
speak, so a plugin can tell from the greeting whether to speak an older one.
