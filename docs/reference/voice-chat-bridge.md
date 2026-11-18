# The voice chat bridge

What a plugin of a voice chat client (see [People](../configuration/channels/people.md#voice-chat)) and the daemon
say to each other, for a plugin of another client than Mumble.

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
