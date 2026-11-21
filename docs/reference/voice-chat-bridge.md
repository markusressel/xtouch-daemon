# The voice chat bridge

What a plugin of a voice chat client (see [People](../configuration/channels/people.md#voice-chat)) and the daemon
say to each other, for a plugin of another client than [Mumble](../guides/mumble.md). The messages are also a
[JSON Schema](https://json-schema.org/), [voice-chat-bridge.schema.json](../voice-chat-bridge.schema.json), made from
the models in the daemon. Its descriptions say what each key means. `xtouch-daemon schema --bridge` prints the schema
of the installed version.

## Connection

The daemon serves the Unix socket `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock` (mode 0600). Each side sends one JSON
object per line. When a plugin connects, the daemon says who it is and which version of the protocol it speaks:

```json
{"daemon": "xtouch-daemon", "version": "0.1.0", "protocol": 1}
```

One plugin per client, and plugins of several clients at once, e.g. Mumble and TeamSpeak. The client is the
`client` of the first state line of a connection; a plugin that sends none counts as one more client. While a plugin
of that client is connected, the daemon refuses the new one: the connected plugin stays, and the new one gets this
line and is closed:

```json
{"error": "another mumble plugin is connected"}
```

Two instances of a client with the plugin enabled would otherwise take the socket from each other. Before its first
state line, a connection keeps no other one out. When a plugin goes, so do the participants of its client, and the
next plugin of that client can connect.

The daemon puts the people of all clients together. Inside the daemon, the id of a participant has the client in
front, e.g. `mumble:12`, so the same id in two clients is two people. A plugin sees only its own ids.

## State

The plugin sends its whole state on every change. While someone talks, it also sends it for the levels, e.g. 20
times a second:

```json
{"protocol": 1, "client": "mumble", "channel": "Lobby", "capabilities": ["volume", "mute", "levels"],
 "participants": [{"id": "12", "name": "Alice", "talking": true, "muted": false, "volume": 100, "level": 0.4,
                   "pre_fader_level": 0.8}]}
```

| Key | Value |
|---|---|
| `protocol` | The version of the protocol, 1 without it. |
| `client` | The voice chat client, e.g. `mumble`. The log and the GUI name it. |
| `channel` | The channel the user is in. The GUI shows it. |
| `capabilities` | What the plugin can do: `volume` (the faders set volumes), `mute` (Mute mutes), `levels` (it sends levels). |
| `participants` | The participants in the channel of the user, in the order they came. Needed. |

A participant:

| Key | Value |
|---|---|
| `id` | What the client knows the participant by, text or a number. Needed. The commands send it back as text. |
| `name` | The name on the LCD. The daemon keeps volume and mute by it. Needed. |
| `talking` | `true` while the participant talks: the LCD lights in `talking_color`. |
| `muted` | `true` while the user muted the participant for themselves (Mumble's local mute). Mute lights. |
| `volume` | The volume of the participant for the user, in percent, 0 to 200; 100 without it. The fader shows it. |
| `level` | How loud the participant talks after their volume, 0 to 1: the peak since the line before. |
| `pre_fader_level` | How loud the participant talks before their volume, 0 to 1. |

With `meter_point = "pre_fader"` (the default), the meter of the strip shows `pre_fader_level`: it stays up while the
fader is down. With `post_fader`, it shows `level`. Without `pre_fader_level`, the meter shows `level` either way.
Leave out a level that the client can't tell.

The daemon clamps a volume or a level that is out of range, and rounds the volume. It ignores (and logs) a line that
is not JSON, or that has a participant without `id` or `name`.

## Commands

The daemon sends commands back the same way, without spaces:

```json
{"set_volume": {"id": "12", "volume": 80}}
{"set_muted": {"id": "12", "muted": true}}
```

`set_volume` needs the capability `volume`, `set_muted` needs `mute`. A command goes to the plugin of the
participant, with the id that the plugin sent. The strip of a person uses the capabilities of the client of that
person.

## Versions

Both sides ignore keys they don't know, so new optional keys keep the version. A change that an older side would get
wrong gets a new `protocol` number. The daemon ignores (and logs) the lines of a protocol it does not speak. A plugin
can tell from the greeting whether to speak an older one.
