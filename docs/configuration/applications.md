# Applications: `apps` and `auto` strips

Application strips control the playback streams of applications, like the per-application sliders in pavucontrol.
They need no setup in PipeWire.

## `apps` strips

All playback streams of a group of applications.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"apps"`. |
| `match` | required | Parts of application names or binaries, ignoring case. |
| `label` | required | The top line of the LCD. |
| `encoder` | `"media"` | `media`, `volume`, `balance` or `homeassistant`, see [Encoders](encoders.md). |

They also have the [options of every audio strip](strips.md#options-of-every-audio-strip): `color`, `meter`, `rec`,
`solo`, `min_volume`, `max_volume`, `fader`, `id`.

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
| Encoder | See [Encoders](encoders.md), for all streams. |
| Mute | Mutes all streams, or unmutes them when all are muted. The LED is on while all are muted. |
| Select | Nothing. |
| LCD | Top: the label. Bottom: the volume, `muted`, or `idle` while no stream of the group is there. |
| Ring | What the encoder controls. |
| Meter | The level of all streams of the group together. |

While no stream of the group is there (e.g. the application was closed), the LCD is dark and shows `idle`, and the
fader glides slowly to the bottom and does nothing. The strip keeps its volume while the daemon runs: when a stream
comes back, the fader goes up to it and the stream gets it.

## `auto` strips

The next application that plays and has no strip of its own.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"auto"`. |
| `encoder` | `"pick"` | `pick`, `media`, `volume`, `balance` or `homeassistant`, see [Encoders](encoders.md). |

They also have the [options of every audio strip](strips.md#options-of-every-audio-strip). There is no `label`: the
label is the application's alias from [`[aliases]`](behavior.md#aliases), or its name.

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
- A newly assigned application keeps its own volume.

With the default `encoder = "pick"`, the encoder chooses the application and a push pins it, so it stays after it
stopped playing. See [Encoders](encoders.md#pick).

An `auto` strip works like an `apps` strip for its application. Without an application it is dark, blank, and does
nothing.
