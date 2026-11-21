# Applications: `apps` channels and `auto`

A strip can control the volume of the applications that play sound, like the per-application sliders in pavucontrol.
There are two ways:

- An `apps` channel is a group of applications that you name, for example every browser. See
  [`apps` channels](#apps-channels).
- The pools `apps` and `auto` put each application that plays on a strip of its own. See
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

They also have the [options of every audio channel](index.md#options-of-every-audio-channel) and
[`in_pool`](index.md#options-for-slots). This example puts the channel `voip` on strip 2:

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
play, and which channel or slot takes each one. A stream can belong to several `apps` channels; the one whose fader
you moved last wins.

[Presets](../presets.md) such as `@browsers` stand for the names of well-known applications of a group. Mix them
with names of your own: `match = ["@voip", "my-voice-app"]`.

| Element | Function |
|---|---|
| Fader | Sets every stream of the group to the same volume, also a stream that starts later. Shows the loudest stream. |
| Encoder | [Encoders](../strip/encoders.md), for all streams. |
| Mute | Mutes all streams, or unmutes them when all are muted. The [LED](../strip/leds.md) is on while all are muted. |
| Select | With `launch`, starts the application: see [Launching the application](#launching-the-application). Else nothing. |
| Meter | The level of all streams together. |

While no stream of the group is there, the backlight is dark, the LCD says `idle` and the fader glides to the bottom.
The channel remembers its volume while the daemon runs: when a stream comes back, the fader goes up to it and the
stream plays at that volume.

## `apps` and `auto`

A [pool](../slots.md#pools-of-applications-and-of-people) hands out applications that you don't list one by one:
`apps` hands out the applications that play, one per slot. `auto` hands out the same applications and the people of
the voice chat share its slots (the people from the right, the applications from the left, see
[People](people.md#where-people-sit)). A slot without an entry shows `auto`.

```toml
[pool.apps]
from = "left"                 # the side the applications fill their slots from (also in auto)
hold = 5                      # seconds an application keeps its slot after it stopped playing
exclude = ["notification"]    # never these, in apps and auto (replaces the default, speech-dispatcher)
color = "cyan"                # the look of every apps slot

[pool.auto]
color = "cyan"                # the look of the applications on every auto slot

[slots]
5 = [{ show = "auto", encoder = "media", max_volume = 100 }]   # the options of one place
6 = ["people", "apps"]        # a person, else an application
```

What a pool can set:

- The look options of an audio channel ([list](index.md#where-else-the-options-work)) go into `[pool.apps]`,
  `[pool.auto]` or a place of a slot, as the example shows. A place of `apps` or `auto` also takes `encoder`,
  `min_volume` and `max_volume`. For a pool, `encoder` is `pick` by default (an `apps` channel has `media`): `pick`,
  `media`, `volume` or `balance`, see [Encoders](../strip/encoders.md).
- A pool has no `label`: a strip shows the application's alias from [`[aliases]`](../behavior.md#aliases), or its
  name.
- To give the encoder or fader of such a slot to [Home Assistant](../../guides/home-assistant.md), use
  [`[controls]`](../slots.md#controls-and-the-chord), not the place:

  ```toml
  [controls]
  5 = { encoder = "homeassistant" }   # the encoder of slot 5 is an entity in Home Assistant
  ```

How `apps` and `auto` get their applications:

- An application qualifies while at least one of its streams plays (is not paused).
- Applications of an `apps` channel that has a slot never go to `apps` or `auto`. Neither do those of `exclude`.
- An `apps` channel without a slot goes in as a whole, on one strip. `in_pool = false` keeps it out.
- Free slots take new applications from the side of `from`, in the order the applications started.
- When the pool has no application for a slot, the slot shows its next candidate.
- An application keeps its slot while it plays and for `hold` seconds after it stopped, so a music player does not
  jump to another strip between two tracks.
- A newly assigned application keeps its own volume.

With the default `encoder = "pick"`, the encoder chooses the application and a push pins it, so it stays after it
stopped playing. See [Encoders](../strip/encoders.md#pick).

A slot of `apps` or `auto` controls its application like an `apps` channel does. Without an application the strip
is dark and does nothing.

## Launching the application

With `launch`, the Select button of an `apps` channel starts an application while it does not run, such as Mumble
or your music player. Any slot can do it with [`[controls]`](../slots.md#controls-and-the-chord), whatever it
shows. Here Select on strip 7 starts Mumble while the [state](../slots.md#states-and-modes) `call` is off (in
`[controls]` a condition is `when = "..."`):

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

- `launch` is the program and its arguments, as a list. A single string works too and is split like a shell
  splits it, with quotes. Nothing runs through a shell: no `~`, `$VARIABLES`, pipes or `&&`.
- Select starts the command only while the application does not run. It counts as running when:
    - A stream matches `match`.
    - A process runs whose name contains one of the `match` entries (like `processes` of
      [states](../slots.md#states-and-modes)). So a voice chat that makes no sound counts as running. A
      [preset](../presets.md) brings its processes, such as `reaper` for `@steam-games`.
    - A process runs whose name is the program of `launch` (the file name of its first part, for example `mumble`).
      A `launch` in `[controls]` has no `match`, so this is the only check there.
- While it runs, Select does nothing. With `launch_when_running = true` Select starts the command also then.
- The Select LED flashes while the application starts (at most 15 s), then is on while it runs. A second press
  within 5 s does nothing.
- The application runs as a transient systemd user service (`systemd-run --user`), so a restart of the daemon does
  not end it. Its output is in `journalctl --user -u 'xtouch-launch-*'`. Without a systemd user manager it starts
  as a separate process. A program that is not in `PATH` is a warning in the log.
- Only the configuration can start programs, not Home Assistant or MQTT. Only `apps` channels and `[controls]`
  have `launch`.

### Mumble

[Mumble](../../guides/mumble.md) connects to a server and joins a channel when it gets a `mumble://` URL
([Mumble's documentation](https://www.mumble.info/documentation/user/mumble-url/)):

```
mumble://[username[:password]@]<address>[:port]/[channel[/subchannel...]]
```

- The port is 64738 by default. Encode special characters of channel names (`Gaming%20Night`). If the channel can't
  be joined, Mumble stays in the default channel.
- A running Mumble takes the URL too, so `launch_when_running = true` makes Select connect it to the server, and
  `launch = ["mumble"]` without a URL brings its window to the front.
- Leave the password out: the configuration file and the process list would show it.
- For Mumble as a Flatpak (`launch = ["flatpak", "run", "info.mumble.Mumble", "mumble://..."]`), keep `mumble` in
  `match`: the program of `launch` is `flatpak` then.

Next: [People](people.md), [Presets](../presets.md), or the [slots](../slots.md) that show them.
