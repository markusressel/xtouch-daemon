# People and the voice chat

The people of the voice chat come from the provider of [`[voip]`](#voice-chat) (by default the Mumble plugin). They
share the `auto` slots with the applications: people take them from the right, in their order, applications from
the left (see [Slots](slots.md#slots)). Someone who should always have a strip of their own gets a
[`person` channel](#strips-for-one-person).

```toml
[people]
color = "white"
talking_color = "green"
order = ["Alice", "mum"]    # from the right: these first, then the others as they came

[channel.mum]
type = "person"
person = ["Alice", "alice-phone"]   # the same person, from the desk or the phone
label = "Mum"
```

## The strips of people

`[people]` is the look of the strips of people without a channel of their own, a `person` channel has the same
options:

| Option | Default | Meaning |
|---|---|---|
| `label` | the first name of `person` | The top line of a `person` channel; people without a channel show their name. |
| `color` | `"white"` | The backlight while the person is there and does not talk. Dark while they are away. |
| `talking_color` | `"green"` | The backlight while the person talks. |
| `meter` | `true` | Whether the LED meter shows the person's voice. Without levels from the provider it lights while they talk. The level is after their volume, see [Meters](strips.md#meters). |
| `max_volume` | `behavior.max_volume` | The volume of a person with the fader at the top, 1..200 percent; 100 % is at the 0 dB mark as on the other strips. Above 100 % the voice is louder than Mumble plays it, and may clip. |

`[people]` also has `order`: the people from the right, as names or ids of `person` channels, before the others in
the order the daemon first saw them (it remembers that order across restarts). The strips of people have no `launch`: starting the voice chat is a control of a slot,
e.g. `7 = { select = { launch = ["mumble"] }, when = "not call" }` in [`[controls]`](slots.md#controls-and-the-chord).

The top line shows the name, the bottom line `muted`, the volume while the fader moves, or `talks`. The fader sets
the person's volume and Mute mutes them for you, if the provider can. The daemon remembers the volume and the mute it
set for each name while it runs, and sets them again when that person comes back (the voice chat starts them at
100 % otherwise). A mute changed in the voice chat itself (Mumble's local mute) replaces the one it set.

## Strips for one person

A `person` channel always shows that person, on the slots that name it. The names are the names in the voice chat,
ignoring case, but otherwise exactly (no wildcards, no parts of a name). With several names, the first person of the
provider's order with one of them is on the strip.

While the person is not in the channel, the strip shows the name dark, `away` on the second line and its fader at
the bottom; `"mum if present"` in a slot shows the channel only while they are there. The volume and mute the strip
set stay with the name while they are away and come back with them. A `person` channel without a slot joins the
people of `auto` as itself (`in_auto = false` keeps it out).

## Voice chat

`[voip]` says where the people come from:

| Option | Default | Meaning |
|---|---|---|
| `provider` | `"bridge"` | `bridge`: a plugin of the voice chat client sends them (see below). `demo`: people who are not there and talk in turns, to try the strips of people. |
| `participants` | `["Alice", "Bob", "Carol", "Dave", "Eve"]` | The names of the `demo` people. |

Without the section, its defaults apply. None of the voice chat clients tells another program the volume of each
person, so the daemon can't read them from PipeWire: they all come out of one stream. Mumble and TeamSpeak have
plugins that can, and the bridge is what such a plugin talks to. For Mumble there is one: see
[Mumble](../integrations/mumble.md), which the GUI installs with a click.

The state `voice_chat = true` (see [States and modes](slots.md#states-and-modes)) is on while you are in a channel of
the voice chat.

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
