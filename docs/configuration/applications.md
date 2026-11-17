# Applications: `apps` channels and `auto`

Application channels and `auto` control the playback streams of applications, like the per-application sliders in pavucontrol.
They need no setup in PipeWire.

## `apps` channels

All playback streams of a group of applications.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"apps"`. |
| `match` | required | Parts of application names or binaries, ignoring case, or [presets](presets.md) like `"@browsers"`. |
| `label` | required | The top line of the LCD. |
| `encoder` | `"media"` | `media`, `volume`, `balance` or `homeassistant`, see [Encoders](encoders.md). |
| `launch` | none | A command that Select starts while none of the applications runs, see [Launching the application](#launching-the-application). |
| `launch_when_running` | `false` | Select starts `launch` also while the application runs. |

They also have the [options of every audio channel](strips.md#options-of-every-audio-channel): `color`, `meter`,
`rec`, `solo`, `min_volume`, `max_volume`, `fader`.

```toml
[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "white"
```

A stream belongs to the channel when its application name (`application.name`) or binary
(`application.process.binary`) contains one of the `match` entries. `"wine"` matches `wine64-preloader`, `".exe"`
matches Windows games under Proton. `xtouch-daemon list-apps` shows the names and binaries of the applications that
play, and which channel or slot takes each one. A stream can belong to several `apps` channels.

For common groups there are [presets](presets.md): `@browsers`, `@voip`, `@games`, `@steam-games`, `@music` and
`@video` stand for the names of well-known applications of the group, e.g. `match = ["@browsers"]` for every browser,
and mix with names of your own (`match = ["@voip", "my-voice-app"]`).

| Element | Function |
|---|---|
| Fader | Sets every stream of the group to the same volume. A stream that starts later gets that volume too. Shows the loudest stream. |
| Encoder | See [Encoders](encoders.md), for all streams. |
| Mute | Mutes all streams, or unmutes them when all are muted. The LED is on while all are muted. |
| Select | Nothing, or with `launch` it starts the application. The LED flashes while it starts and is on while it runs, see [Launching the application](#launching-the-application). |
| LCD | Top: the label. Bottom: the volume, `muted`, or `idle` while no stream of the group is there. |
| Ring | What the encoder controls. |
| Meter | The level of all streams of the group together. |

While no stream of the group is there (e.g. the application was closed), the LCD is dark and shows `idle`, and the
fader glides slowly to the bottom and does nothing. The channel keeps its volume while the daemon runs: when a stream
comes back, the fader goes up to it and the stream gets it.

## `auto`

The next application that plays and has no channel of its own, on the slots that show `auto` (a slot without an
entry shows it too). People of the voice chat share these slots, from the right (see [People](people.md)).

```toml
[pool.auto]
hold = 5                      # seconds an application keeps its slot after it stopped playing
exclude = ["notification"]    # never these (by default speech-dispatcher)
color = "cyan"                # the look of every auto slot

[slots]
5 = [{ show = "auto", encoder = "media", max_volume = 100 }]   # the options of one place
```

The look options of every audio channel go into `[pool.auto]` or a place; a place of `auto` also takes `encoder`
(`pick` by default: `pick`, `media`, `volume`, `balance` or `homeassistant`, see [Encoders](encoders.md)),
`min_volume` and `max_volume`. There is no `label`: the label is the application's alias from
[`[aliases]`](behavior.md#aliases), or its name.

How `auto` gets its applications:

- An application qualifies while at least one of its streams plays (is not paused).
- Applications of an `apps` channel with a slot, and those of `exclude`, never go to `auto`; an `apps` channel
  without a slot goes into `auto` as a whole (`in_auto = false` keeps it out).
- Free `auto` slots take new applications from the left, in the order the applications started.
- An application keeps its slot while it plays, and for `hold` seconds after it stopped. Then the slot is free
  again. This way a music player does not jump to another strip between two tracks.
- A newly assigned application keeps its own volume.

With the default `encoder = "pick"`, the encoder chooses the application and a push pins it, so it stays after it
stopped playing. See [Encoders](encoders.md#pick).

An `auto` slot works like an `apps` channel for its application. Without an application it is dark, blank, and does
nothing.

## Launching the application

With `launch`, the Select button of an `apps` channel starts an application while it does not run: the voice
chat, the music player. Any slot can start one with [`[controls]`](slots.md#controls-and-the-chord), whatever it
shows: `7 = { select = { launch = ["mumble"] }, when = "not call" }`.

```toml
[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "yellow"
lit_when_idle = true
launch = ["mumble", "mumble://markus@voice.example.org/Gaming"]
```

- `launch` is the program and its arguments, as a list. It never runs through a shell: no `~`, `$VARIABLES`, pipes or
  `&&`. A single string works too (`launch = "mumble mumble://markus@voice.example.org/Gaming"`) and is split like a
  shell splits it, with quotes, but nothing is expanded.
- Select starts it only while the application does not run: no stream matches `match`, and no process whose name
  contains one of the `match` entries runs (like `processes` of [states](slots.md#states-and-modes)), so a silent
  voice chat counts as running. For a [preset](presets.md), its processes count, e.g. Steam's `reaper` for
  `@steam-games`. A process named like the program of `launch` (the file name of its first part, exactly) counts
  too; that is all a launch of `[controls]` looks at.
- While it runs, Select does nothing. With `launch_when_running = true` Select starts the command also then.
- The Select LED flashes while the application starts (until it runs, at most 15 s), then it is on while it runs.
- A second press within 5 s while the application is not up yet does nothing.
- The application runs on its own: as a transient systemd user service (`systemd-run --user`, named
  `xtouch-launch-<program>-<random>`), so a restart of the daemon does not end it, and its output is in
  `journalctl --user -u 'xtouch-launch-*'`. Without a systemd user manager it runs in a session of its own. A
  program that is not in `PATH` is a warning in the daemon's log.
- The process list is read every 2 s.
- Only the configuration can start programs: neither Home Assistant nor MQTT can, and `homeassistant`, `output`,
  `input` and `person` channels have no `launch`.

### Mumble

Mumble connects to a server and joins a channel when it gets a `mumble://` URL
([Mumble's documentation](https://www.mumble.info/documentation/user/mumble-url/)):

```
mumble://[username[:password]@]<address>[:port]/[channel[/subchannel...]]
```

- The port is 64738 by default. Encode spaces and other special characters of channel names (`Gaming%20Night`). If
  the channel can't be joined, Mumble stays in the server's default channel.
- A running Mumble takes the URL too: the new `mumble` hands it to the running one and ends. So
  `launch_when_running = true` makes Select connect a running Mumble to the server, and `launch = ["mumble"]`
  without a URL brings its window to the front.
- Better leave the password out: the configuration file and the process list would show it. Mumble remembers
  servers, and certificates need no password.
- For Mumble as a Flatpak (`launch = ["flatpak", "run", "info.mumble.Mumble", "mumble://..."]`), keep `mumble` in
  `match`: the program of `launch` is `flatpak` then.
