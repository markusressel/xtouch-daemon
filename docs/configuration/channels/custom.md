# Custom channels

A `custom` channel is a strip that controls something other than audio. You connect each part of the strip (fader,
encoder, LCD, meter, buttons) to a program of your own, or to Home Assistant. For example, a fader can set the
brightness of a screen. The examples use [system-control](https://github.com/markusressel/system-control)
(`sysctrl`); any command that sets and prints a number works.

A `custom` channel has no built-in behavior, unlike the fader of an `output` channel, which sets the volume. A part
that you [bind](../strip/bindings.md) (connect to a program or to Home Assistant) works. A part that you leave out
is dark and does nothing, except the encoder and the LCD, which follow the fader (see the table). A slot names the
channel, as for every other type.

This channel puts the brightness of the left screen on a fader. `set` changes the brightness (`{value}` is the new
value). `watch` prints it on each change, so the fader follows changes made elsewhere:

```toml
[channel.screen_left]
type = "custom"
label = "Left"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }

[slots]
7 = "screen_left"    # strip 7 controls it
```

`min` and `max` are the values at the bottom and at the top of the fader. `format` is how the LCD shows the value
(`60%`).

The options of a `custom` channel:

| Option | Default | Meaning |
|---|---|---|
| `label` | The id of the channel, or the name of the target | The top line of the LCD. |
| `color` | `"white"` | The backlight: a [color name](index.md#options-of-every-audio-channel), `"homeassistant"`, or `{ watch = "command" }` or `{ poll = "command", every = 5 }` (the newest line is the color name). |
| `fader` | none: the fader stays down | A value (below), or `"homeassistant"`. |
| `encoder` | a turn changes the fader's value by `step` | A value of its own (below), or `"homeassistant"`; see [Encoders](../strip/encoders.md). Without a fader and an encoder, the ring is dark. |
| `lcd` | The value of the fader, else of the encoder, as its `format` says | The second line: `"homeassistant"`, or `{ watch }` or `{ poll, every }` (the newest line is the text). |
| `meter` | none: dark | `"homeassistant"`, or `{ watch, min, max }` or `{ poll, every, min, max }` (each line is a number from `min` to `max`). |
| `select`, `rec`, `solo`, `mute` | nothing | `press`, `hold` and `led` of the button (below). |
| `present` | always present | `{ watch }`, `{ poll, every }` or `{ entity }`, see [Present](#present). |
| `targets` | none | The things the strip controls one at a time (below). |
| `together` | `false` | A move sets every target at once (below). |

## A value

![The fader of a strip](../../images/controls/fader.png){ .xt-part width="80" }

A value (`fader = { ... }`, `encoder = { ... }`) takes these options; only an encoder has `push`:

| Option | Default | Meaning |
|---|---|---|
| `set` | | A [command](../strip/bindings.md#commands); `{value}` in an argument is the new value, e.g. `0.55`. |
| `watch` | none | A program that runs all the time and prints the value, one line per change. The first number of a line counts. The fader, the ring and the LCD follow it. |
| `poll` | none | Instead of `watch`: a program that runs to its end every `every` seconds and prints the value (the first number of its last line counts). |
| `every` | `10` | Seconds between runs of `poll` ([Watch or poll](../strip/bindings.md#watch-or-poll)). |
| `min`, `max` | `0`, `100` | The value with the fader at the bottom and at the top, the ring empty and full. |
| `step` | `behavior.encoder_step` percent of `max - min` | How much one click of the encoder changes the value, in its unit. Put it in the `encoder` table: `encoder = { set = "...", step = 5 }`. With the default `behavior.encoder_step` of 1 ([`[behavior]`](../behavior.md#behavior)), `min = 0` and `max = 100`, one click is 1. |
| `push` | none | The value that pushing the encoder sets. Without it, a push does nothing. |
| `format` | `{value:g}` | How the LCD shows the value, in the [format of Python](https://docs.python.org/3/library/string.html#formatspec). |

How `set` and `watch` run is in [Values and watches](../strip/bindings.md#values-and-watches). Two things are
specific to `custom` channels:

Without `watch` or `poll`
:   The daemon knows only the values it set itself. Until the first one, the ring is dark and the fader stays where it
    is. A turn of the encoder then starts at `push` if the encoder has one, else at `min`.

With `watch` or `poll`
:   While you touch the fader or while `set` runs, new lines don't move the value.

## Buttons

![The buttons of a strip, lit: Rec and Mute red, Solo yellow, Select green](../../images/controls/buttons.png){ .xt-part width="64" }

Select, Rec, Solo and Mute do nothing until you give them a `press` and, if you want one, a `hold` (it fires after
0.5 seconds). Each button takes a table, as the example below shows. The actions:

| Action | What it does |
|---|---|
| `off` | Nothing. |
| `{ run = "..." }` | Runs a program to its end. `{value}` in it is the value of the fader, else of the encoder. |
| `next` | Switches to the next target. It needs two targets or more, and not `together`. |
| `cycle_modes`, `mode:<id>`, `toggle:<id>` | As on other channels ([Buttons](../strip/leds.md#buttons)). |
| `homeassistant` | Sends an event to Home Assistant for each press and release. Only as `press`; no `hold` then. |

`led` takes:

| `led` | The LED |
|---|---|
| `off` | Stays dark. |
| `press` | Lit while the action of `press` is going on: the program of `run` runs, `next` has switched to another target than the first, or the mode or state of `mode:<id>` or `toggle:<id>` is on. |
| `homeassistant` | Home Assistant sets it. |
| `{ watch }` or `{ poll, every }` | `on`, `1`, `true`, `yes` light it, `flash` flashes it, anything else turns it off. |

```toml
[channel.night]
type = "custom"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0 }
# Select sets full brightness; its LED is lit while the screen is dimmed
select = { press = { run = "sysctrl display redshift brightness reset -d DisplayPort-1" }, led = { watch = "/home/me/bin/screen-dimmed" } }
mute = { press = { run = "notify-send 'Brightness {value}'" }, led = "press" }
```

`/home/me/bin/screen-dimmed` is your own script. It prints `on` while the screen is dimmed, else `off`:

```sh
#!/bin/sh
sysctrl display redshift brightness -d DisplayPort-1 --watch | awk '{ print ($1 < 1 ? "on" : "off"); fflush() }'
```

## Present

With `present`, the channel is a candidate of the slots only while it is there, e.g. a screen that is plugged in.
`present = { watch }` or `{ poll, every }`: a line with text makes it present, an empty line absent. Until the first
line it counts as present. A `poll` that prints no text makes it absent; a run that fails changes nothing. With
`{target}` in the program (see [Targets](#targets)), one watch or poll runs per target, and the channel is present
while any target is.

`present = { entity = "..." }` (see [An entity of Home Assistant](../strip/bindings.md#an-entity-of-home-assistant))
makes it present unless the entity is `unavailable`, `unknown` or missing in Home Assistant, or the daemon is not
connected to it. Before its first try to connect, it counts as present.

## Targets

`targets` are the things the strip controls one at a time, e.g. two screens. Each has a `name` (7 characters at most,
for the LCD) and a `value`. `{target}` in a program is replaced by the `value` of the target the strip controls now
(not the value of the fader). Every target has its own values, watches and polls. A program without `{target}` is
the same for every target and runs once.

```toml
[channel.screens]
type = "custom"
targets = [{ name = "Left", value = "DisplayPort-1" }, { name = "Right", value = "DisplayPort-2" }]
fader = { set = "sysctrl display redshift brightness -d {target} -b {value}", watch = "sysctrl display redshift brightness -d {target} --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }
select = { press = "next", led = "press" }
```

Select switches between the screens. Without a `label`, the top line names the target. With a `label`, the second
line shows the new target's name for 2 seconds after a switch. `{target}` without `targets` is an error, and so are
targets that no program uses.

With `together = true`, a move sets every target at once, and the strip shows the first one.

## Two screens

Two screens can be two channels (`screen_left` as above and `screen_right` with `DisplayPort-2`, on slots 7 and 8),
one strip with two [targets](#targets), or one strip for both at once:

```toml
[channel.screens]
type = "custom"
label = "Screens"
targets = [{ name = "Left", value = "DisplayPort-1" }, { name = "Right", value = "DisplayPort-2" }]
together = true     # a move sets both; the strip shows the left screen
fader = { set = "sysctrl display redshift brightness -d {target} -b {value}", watch = "sysctrl display redshift brightness -d {target} --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }
```

## Home Assistant

A part set to `"homeassistant"` is the entity of that part in Home Assistant, as on a
[`homeassistant` channel](../../guides/home-assistant.md#homeassistant-channels); it needs `[mqtt]`. With `[mqtt]`,
a fader or an encoder bound to a value is also a number in Home Assistant (`number.<ns>_<id>_fader`,
`number.<ns>_<id>_encoder`; `<ns>` is the `namespace` of `[mqtt]`, "xtouch" by default) from `min` to `max`: it shows
the value, and a change there runs `set`. See [Entities](../../guides/home-assistant.md#entities).

## On another slot

[`[controls]`](../slots.md#controls-and-the-chord) gives the fader or the encoder of any slot to the value of a
custom channel, without a slot for the channel. A fader sets the channel's fader value; an encoder sets the
channel's own encoder value, else its fader value. The slot keeps showing what it shows: the encoder of the speaker
strip can set the screen brightness while its fader keeps the speaker's volume. With targets, it controls the target
the channel controls now.

```toml
[controls]
1 = { encoder = { channel = "screen_left" } }   # the encoder of strip 1 sets the value of the channel screen_left
```

## Simulate

Simulate in the GUI and `xtouch-daemon simulate` run `watch` and `poll` programs, but never `set` or `run`: a move
there changes only the simulation. Until the first line, a value is in the middle of its range. `present` comes from
the situation you simulate, not from its watch.
