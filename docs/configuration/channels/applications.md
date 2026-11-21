# Applications: `apps` channels and `auto`

A strip can control the volume of the applications that play sound, like the per-application sliders in pavucontrol.
There are two ways to set that up, and they need no setup in PipeWire:

- An `apps` channel is a group of applications that you name, for example every browser. A slot that
  names the channel decides which strip it is on. See [`apps` channels](#apps-channels).
- The pools `apps` and `auto` put each application that plays on a strip, one application per strip. Applications that an `apps` channel with a slot
  already shows are left out. See
  [`apps` and `auto`](#apps-and-auto).

## `apps` channels

An `apps` channel controls all playback streams of a group of applications at once: one fader sets all of them.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"apps"`. |
| `match` | required | Parts of application names or binaries, ignoring case, or [presets](../presets.md) like `"@browsers"`. |
| `label` | required | The top line of the LCD. |
| `encoder` | `"media"` | `media`, `volume`, `balance` or `homeassistant`, see [Encoders](../strip/encoders.md). |
| `launch` | none | A command that Select starts while the application does not run, see [Launching the application](#launching-the-application). |
| `launch_when_running` | `false` | Select starts `launch` also while the application runs. |

They also have the [options of every audio channel](index.md#options-of-every-audio-channel): `color`, `meter`,
`lit_when_idle`, `meter_point`, `rec`, `solo`, `min_volume`, `max_volume`, `fader`. The option `in_pool` is described in
[Options for slots](index.md#options-for-slots).

A channel appears on a strip when a slot names it. This example puts the channel `voip` on strip 2:

```toml
[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "white"

[slots]
2 = "voip"
```

A stream belongs to the channel when its application name (`application.name`) or binary
(`application.process.binary`) contains one of the `match` entries. `"wine"` matches `wine64-preloader`, `".exe"`
matches Windows games under Proton. `xtouch-daemon list-apps` shows the names and binaries of the applications that
play, and which channel or slot takes each one. A stream can belong to several `apps` channels. The fader of each of them sets its volume, so the one you moved last
wins.

For common groups there are [presets](../presets.md): `@browsers`, `@voip`, `@games`, `@steam-games`, `@music` and
`@video` stand for the names of well-known applications of the group, e.g. `match = ["@browsers"]` for every browser,
and mix with names of your own (`match = ["@voip", "my-voice-app"]`).

| Element | Function |
|---|---|
| Fader | Sets every stream of the group to the same volume. A stream that starts later gets that volume too. Shows the loudest stream. |
| Encoder | See [Encoders](../strip/encoders.md), for all streams. |
| Mute | Mutes all streams, or unmutes them when all are muted. The [LED](../strip/leds.md) is on while all are muted. |
| Select | Nothing, or with `launch` it starts the application. The LED flashes while it starts and is on while it runs, see [Launching the application](#launching-the-application). |
| LCD | Top: the label. Bottom: the volume, `muted`, or `idle` while no stream of the group is there. |
| Ring | The LEDs around the encoder show the value the encoder sets. |
| Meter | The level of all streams of the group together. |

While no stream of the group is there (for example the application was closed), the backlight is dark and the bottom line of the LCD says `idle`.
The fader glides slowly to the bottom and does nothing. The channel remembers its volume while the daemon runs. When
a stream of the group comes back, the fader goes up to that volume again, and the new stream plays at that volume.

## `apps` and `auto`

A **pool** hands out applications that you don't list one by one. Each slot that names the pool gets the next
application.

- The pool `apps` hands out the applications that play and that no `apps` channel with a slot shows, one per slot.
- The pool `auto` hands out the same applications, and the people of the voice chat share its slots. The people fill
  the slots from the right, the applications from the left (see [People](people.md#where-people-sit)).

A slot without an entry shows `auto`.

```toml
[pool.apps]
from = "left"                 # the side the applications fill their slots from (also in auto)
hold = 5                      # seconds an application keeps its slot after it stopped playing
exclude = ["notification"]    # never these (replaces the default, speech-dispatcher)
color = "cyan"                # the look of every apps slot

[pool.auto]
color = "cyan"                # the look of the applications on every auto slot

[slots]
5 = [{ show = "auto", encoder = "media", max_volume = 100 }]   # the options of one place
6 = ["people", "apps"]        # a person, else an application
```

What a pool can set:

- The look options of an audio channel (`color`, `lit_when_idle`, `meter`, `meter_point`, `rec`, `solo`, see
  [Options of every audio channel](index.md#options-of-every-audio-channel)) go into `[pool.apps]`, `[pool.auto]` or
  a place of a slot, as the example shows.
- A place is one candidate of a slot written as a table (`{ show = "auto", ... }`). A place of `apps` or `auto` also takes `encoder`, `min_volume` and `max_volume`. For a pool, `encoder` is `pick`
  by default (an `apps` channel has `media`): `pick`, `media`, `volume` or `balance`, see
  [Encoders](../strip/encoders.md).
- A pool has no `label`. The label of a strip is the application's alias from [`[aliases]`](../behavior.md#aliases),
  or its name.
- To give the encoder or fader of such a slot to [Home Assistant](../../guides/home-assistant.md), use the section
  [`[controls]`](../slots.md#controls-and-the-chord), not the place:

  ```toml
  [controls]
  5 = { encoder = "homeassistant" }   # the encoder of slot 5 is an entity in Home Assistant
  ```

How `apps` and `auto` get their applications:

- An application qualifies while at least one of its streams plays (is not paused).
- Applications of an `apps` channel that has a slot never go to `apps` or `auto`. Neither do those of `exclude`.
- An `apps` channel without a slot goes in as a whole: all its streams on one strip. `in_pool = false` on the channel
  keeps it out.
- Free slots take new applications from the side of `from` (the left by default), in the order the applications
  started.
- When the pool has no application for a slot, the slot shows the next candidate in its list. In
  `["apps", "people"]` that is a person.
- An application keeps its slot while it plays, and for `hold` seconds after it stopped. Then the slot is free
  again. This way a music player does not jump to another strip between two tracks.
- A newly assigned application keeps its own volume.

With the default `encoder = "pick"`, the encoder chooses the application and a push pins it, so it stays after it
stopped playing. See [Encoders](../strip/encoders.md#pick).

A slot of `apps` or `auto` controls its application like an `apps` channel does (fader, Mute, meter), except that the
application keeps its own volume when the slot takes it. Without an application the strip is dark and does nothing.

## Launching the application

With `launch`, the Select button of an `apps` channel starts an application while it does not run: the voice
chat, the music player. Any slot can start one with [`[controls]`](../slots.md#controls-and-the-chord), whatever it
shows. In `[controls]` a condition is written as `when = "..."`; in a slot you write it after `if`. In this example, Select on strip 7 starts Mumble while the state `call` (a state you define, see [States](../slots.md#states-and-modes)) is off:

```toml
[controls]
7 = { select = { launch = ["mumble"] }, when = "not call" }
```

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
- Select starts the command only while the application does not run. The daemon calls it running when one of these
  holds:
    - A stream matches `match`.
    - A process runs whose name contains one of the `match` entries (like `processes` of
      [states](../slots.md#states-and-modes)). So a voice chat that makes no sound counts as running. For a
      [preset](../presets.md) the processes of the preset count, for example Steam's helper process `reaper` for `@steam-games`.
    - A process runs whose name is the program of `launch` (the file name of its first part, for example `mumble`).
      A `launch` in `[controls]` has no `match`, so this is the only check there.
- While it runs, Select does nothing. With `launch_when_running = true` Select starts the command also then.
- The Select LED flashes while the application starts (until it runs, at most 15 s), then it is on while it runs.
- A second press within 5 s while the application is not up yet does nothing.
- The application runs on its own: as a transient systemd user service (`systemd-run --user`, named
  `xtouch-launch-<program>-<random>`), so a restart of the daemon does not end it, and its output is in
  `journalctl --user -u 'xtouch-launch-*'`. Without a systemd user manager it starts as a separate process that the daemon does not wait for. A
  program that is not in `PATH` is a warning in the daemon's log.
- The process list is read every 2 s.
- Only the configuration can start programs: neither Home Assistant nor MQTT can, and `homeassistant`, `output`,
  `input` and `person` channels have no `launch`.

### Mumble

[Mumble](../../guides/mumble.md) connects to a server and joins a channel when it gets a `mumble://` URL
([Mumble's documentation](https://www.mumble.info/documentation/user/mumble-url/)):

```
mumble://[username[:password]@]<address>[:port]/[channel[/subchannel...]]
```

- The port is 64738 by default. Encode spaces and other special characters of channel names (`Gaming%20Night`). If
  the channel can't be joined, Mumble stays in the server's default channel.
- A running Mumble takes the URL too: a second `mumble` that you start hands the URL to the running one and ends. So
  `launch_when_running = true` makes Select connect a running Mumble to the server, and `launch = ["mumble"]`
  without a URL brings its window to the front.
- Leave the password out: the configuration file and the process list would show it. Mumble remembers
  servers, and certificates need no password.
- For Mumble as a Flatpak (`launch = ["flatpak", "run", "info.mumble.Mumble", "mumble://..."]`), keep `mumble` in
  `match`: the program of `launch` is `flatpak` then.

Next: [People](people.md), [Presets](../presets.md), or the [slots](../slots.md) that show them.
