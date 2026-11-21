# The voice chat bridge

The bridge is how a plugin that runs inside a voice chat program (a "client", e.g. Mumble) and the daemon talk to each
other. Read this page if you write a plugin for a client other than [Mumble](../guides/mumble.md) or
[TeamSpeak](../guides/teamspeak.md); to use the strips of people, see [People](../configuration/channels/people.md#voice-chat).
The plugin tells the daemon who is in the user's channel and who talks. The daemon tells the plugin to set a volume
or a mute. A working example is the [Mumble plugin](../development/mumble-plugin.md) (its sources are in
`integrations/mumble`). The messages are also a
[JSON Schema](https://json-schema.org/), [voice-chat-bridge.schema.json](../voice-chat-bridge.schema.json), made from
the models in the daemon. Its descriptions say what each key means. `xtouch-daemon schema --bridge` prints the schema
of the installed version.

## Connection

The daemon serves the Unix socket `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock` (mode 0600, so only your user can
connect). Each side sends one JSON object per line, in UTF-8. When a plugin connects, the daemon sends a greeting
first. It says who it is and which version of the protocol it speaks:

```json
{"daemon": "xtouch-daemon", "version": "0.1.0", "protocol": 1}
```

The daemon accepts one plugin for each client, and plugins of several clients at the same time, e.g. Mumble and
TeamSpeak. The plugin names its client in the key `client` of its first state line (see [State](#state)). If the key is
missing, the daemon uses the name "a client": all such plugins share that one name, so only one of them can be
connected at a time. A connection that has not sent a state line yet has no client, and keeps nobody else out.

While a plugin of a client is connected, the daemon refuses a second plugin of the same client: the connected plugin
stays, and the new one gets this line and the daemon closes its connection. The line names the client
(`another plugin is connected` without a name):

```json
{"error": "another mumble plugin is connected"}
```

The daemon does this because two instances of a client with the plugin enabled (e.g. two Mumble programs) would
otherwise take the connection from each other, again and again. When a plugin disconnects, the daemon drops the
participants of its client, and the next plugin of that client can connect.

The daemon puts the people of all clients together. Inside the daemon, the id of a participant gets the client in
front, e.g. `mumble:12`, so the same id in two clients is two people. A plugin never sees this: it sends and
receives only its own ids.

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
| `protocol` | The version of the protocol that the plugin speaks. Optional: the daemon takes 1 if the key is missing. |
| `client` | The name of the voice chat client, e.g. `mumble`. Any text; the log and the GUI show it, and the daemon uses it to allow one plugin for each client. Send the same name every time. |
| `channel` | The channel the user is in. The GUI shows it. |
| `capabilities` | What the plugin can do besides telling who is there and who talks: `volume` (a fader sets the volume of a person: the daemon may send `set_volume`), `mute` (the Mute button mutes a person: the daemon may send `set_muted`), `levels` (the plugin sends `level`, and the meter shows it). A strip of a person has no fader function or no Mute function when the plugin does not list the capability. |
| `participants` | The participants in the channel of the user, without the user, in the order they came. Needed. |

A participant:

| Key | Value |
|---|---|
| `id` | What the client knows the participant by, text or a number. Needed. The commands send it back as text. |
| `name` | The name on the LCD. Needed. The daemon remembers the volume and the mute that the faders and Mute set for each name, while it runs, and sends them again when a participant with that name comes back. Two participants with the same name share what it remembers. |
| `talking` | `true` while the participant talks. The backlight of the LCD then has the color `talking_color` of the strip (the strips of people have this option, see [People](../configuration/channels/people.md#the-strips-of-people)). |
| `muted` | `true` while the user has muted this participant, for themselves only (in Mumble: the local mute). The Mute LED of the strip then lights. |
| `volume` | The volume of the participant for the user, in percent, 0 to 200; 100 without it. The fader shows it. |
| `level` | How loud the participant talks after their volume, 0 to 1: the peak since the previous state line of the plugin. |
| `pre_fader_level` | How loud the participant talks before their volume, 0 to 1 (the same peak since the previous state line). |

The option `meter_point` of the strip of the person (default: `behavior.meter_point`, which is `"pre_fader"`) picks
the level. With `"pre_fader"`, the meter shows `pre_fader_level`: it stays up while the fader is down. With
`"post_fader"`, it shows `level`. If the plugin sends no `pre_fader_level`, the meter shows `level` either way. If the
client cannot measure a level, leave the key out.

The daemon clamps a volume or a level that is out of range, and rounds the volume. It ignores (and logs) a line that
is not JSON, or that has a participant without `id` or `name`.

## Commands

The daemon sends commands to the plugin the same way: one JSON object per line. It writes them without spaces (you
can parse them with any JSON reader):

```json
{"set_volume": {"id": "12", "volume": 80}}
{"set_muted": {"id": "12", "muted": true}}
```

`set_volume` needs the capability `volume`, `set_muted` needs `mute`. A command goes to the plugin that reported the
participant, with the `id` that this plugin sent (as text, also if it sent a number). The daemon sends a command only
if the plugin of that person lists the capability; otherwise the fader or Mute of the strip does nothing to the
voice chat.

When a user changes the volume in the client itself, the plugin reports it in its next state line (`volume`).

## Versions

Both sides ignore keys they don't know, so a new optional key keeps the version. A change that an older side would
get wrong gets a new `protocol` number. At present the only version is 1. The daemon ignores (and logs) a state line
whose `protocol` it does not speak, so a plugin of a newer protocol has no effect on an older daemon. The `protocol` of the
greeting is how a plugin finds out which version the daemon speaks; a plugin can then send the lines of that version
if it knows it.
