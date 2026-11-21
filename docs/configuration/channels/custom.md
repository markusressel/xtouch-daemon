# Custom channels

A `custom` channel is a strip whose parts you bind to programs of your own, or to Home Assistant, e.g. a fader that
sets the brightness of a screen (the examples use [system-control](https://github.com/markusressel/system-control), `sysctrl`). It has no defaults: every part it uses is [bound](../strip/bindings.md), the others
are dark and do nothing. It works like any other channel: a candidate in the [slots](../slots.md#slots), a member of
pools.

```toml
[channel.screen_left]
type = "custom"
label = "Left"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }
```

| Option | Default | Meaning |
|---|---|---|
| `label` | The id of the channel, or the name of the target | The top line of the LCD. |
| `color` | `white` | The backlight of the LCD: a color name, `"homeassistant"`, or `{ watch }` (each line is a color name). |
| `fader` | none: the fader stays down | A value (below), or `"homeassistant"`. |
| `encoder` | the value of the fader, by its `step` | A value of its own (below), or `"homeassistant"`; see [Encoders](../strip/encoders.md). Without a fader and an encoder, the ring is dark. |
| `lcd` | the value of the fader, else of the encoder, in its `format` | The second line of the LCD: `"homeassistant"`, or `{ watch }` (each line is the text). |
| `meter` | none: the meter is dark | `"homeassistant"`, or `{ watch, min, max }` (each line is a level from `min` to `max`). |
| `select`, `rec`, `solo`, `mute` | nothing | `press`, `hold` and `led` of the button (below). |
| `present` | always present | `{ watch }`: a line with text makes the channel present, an empty line absent. `{ entity }`: present unless the entity is `unavailable` or `unknown`. |
| `targets` | none | The things the strip controls one at a time (below). |
| `together` | `false` | A move sets every target at once (below). |

## A value

A value (`fader = { ... }`, `encoder = { ... }`) takes these options; only the encoder has a `push`:

| Option | Default | Meaning |
|---|---|---|
| `set` | | The program that sets the value, then each argument; `{value}` in an argument is the new value, e.g. `0.55`. A string is split like a shell does, but nothing is expanded. |
| `watch` | none | A program that runs all the time and prints the value, one line per change. The first number of a line counts. The fader, the ring and the LCD follow it. |
| `min`, `max` | `0`, `100` | The value with the fader at the bottom and at the top, the ring empty and full. |
| `step` | `behavior.encoder_step` percent of the range | How much one step of the encoder changes the value; on a fader, of the encoder that sets its value. Also the step of its number in Home Assistant. |
| `push` | none | The value a push of the encoder sets. Without it, a push does nothing. |
| `format` | `{value:g}` | How the LCD shows the value, in the [format of Python](https://docs.python.org/3/library/string.html#formatspec). |

The fader, the ring and the LCD show a change at once. The program runs with the newest value only: turns and moves
that come while it runs wait for it, and only the last of them runs next. A program that fails or takes longer than 10
seconds is logged as a warning.

Without `watch` the daemon knows only the values it set. Until the first one, the ring is dark, the fader stays where
it is, and a turn starts from `push`, or else from `min`. While a value is set or a fader of it is under a finger, the
lines of `watch` don't move it. A `watch` that ends or can't start runs again after 5 seconds.

A `watch` runs for as long as the configuration, also while no slot shows the channel.

## Buttons

Select, Rec, Solo and Mute do nothing until you give them a `press` (and a `hold`, once the button is down for
0.5 seconds):

| Action | What it does |
|---|---|
| `off` | Nothing. |
| `{ run = "..." }` | Runs a program to its end. `{value}` in it is the value of the fader, else of the encoder. |
| `next` | Switches to the next target. It needs two targets or more, and not `together`. |
| `cycle_modes`, `mode:<id>`, `toggle:<id>` | As on the other channels ([Buttons](../strip/leds.md#buttons)). |
| `homeassistant` | An event in Home Assistant per press and release; as `press` only, without a `hold`. |

`led` is `off`, `press` (lit while the program of `run` runs, while another target than the first is on with `next`,
while the mode or the state of the press is on), `homeassistant`, or `{ watch }` (`on`, `1`, `true`, `yes` light it,
`flash` flashes it, anything else turns it off).

```toml
[channel.night]
type = "custom"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0 }
# Select sets the full brightness; its LED is lit while the screen is dimmed
select = { press = { run = "sysctrl display redshift brightness reset -d DisplayPort-1" }, led = { watch = ["sh", "-c", "sysctrl display redshift brightness -d DisplayPort-1 --watch | awk '{ print ($1 < 1 ? \"on\" : \"off\"); fflush() }'"] } }
mute = { press = { run = "notify-send 'Brightness {value}'" }, led = "press" }
```

## Present

With `present`, the channel is a candidate of the slots only while it is there, e.g. a screen that is plugged in:
a line with text makes it present, an empty line absent. Until the first line, it counts as present. With `{target}`
in it, one watch runs per target, and the channel is present while any of its targets is. With `{ entity = "..." }`
(see [An entity of Home Assistant](../strip/bindings.md#an-entity-of-home-assistant)), it is present unless the entity
is `unavailable` or `unknown`, or Home Assistant does not have it; while the daemon is not connected to Home Assistant
it is absent, before the first connection it counts as present.

## Targets

`targets` are the things the strip controls one at a time, e.g. two screens. Each has a `name` (7 characters at most,
for the LCD) and a `value`; `{target}` in the programs is the value of the target the strip controls. Every target
has its own values and watches. A program without `{target}` is the same for every target and runs once.

```toml
[channel.screens]
type = "custom"
targets = [{ name = "Left", value = "DisplayPort-1" }, { name = "Right", value = "DisplayPort-2" }]
fader = { set = "sysctrl display redshift brightness -d {target} -b {value}", watch = "sysctrl display redshift brightness -d {target} --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }
select = { press = "next", led = "press" }
```

Select switches between the screens. Without a `label`, the top line of the LCD names the target; with a `label`, the
second line shows the name of the new target for 2 seconds, then its value again (a hand on the strip shows the value
at once). `{target}` without `targets` is an error, and so are targets that no program uses.

With `together = true`, a move sets every target at once, and the strip shows the first one, e.g. both screens at
the same brightness.

## Two screens

Three ways to set the brightness of two screens. `sysctrl ... --watch` prints the brightness, e.g. `0.60`, at each
change; the range is 0.1 to 1.0.

As two channels, each a strip of its own, e.g. on slots 7 and 8:

```toml
[channel.screen_left]
type = "custom"
label = "Left"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }

[channel.screen_right]
type = "custom"
label = "Right"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-2 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-2 --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }

[slots]
7 = "screen_left"
8 = "screen_right"
```

As one strip with two targets: Select switches between the screens, its LED is lit on the second one. This is the
example of [Targets](#targets).

As one strip for both screens at once: with `together`, a move sets both, and the strip shows the left screen.

```toml
[channel.screens]
type = "custom"
label = "Screens"
targets = [{ name = "Left", value = "DisplayPort-1" }, { name = "Right", value = "DisplayPort-2" }]
together = true
fader = { set = "sysctrl display redshift brightness -d {target} -b {value}", watch = "sysctrl display redshift brightness -d {target} --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }
```

## Home Assistant

A part set to `"homeassistant"` is the entity of that part in Home Assistant, as on a
[`homeassistant` channel](../../guides/home-assistant.md#homeassistant-channels); it needs `[mqtt]`. With `[mqtt]`,
a fader or an encoder bound to a value is also a number in Home Assistant (`number.<ns>_<id>_fader`,
`number.<ns>_<id>_encoder`), from `min` to `max`: it shows the value, and a change there runs `set`. See
[Entities](../../guides/home-assistant.md#entities).

## On another slot

`[controls]` can give the fader or the encoder of any slot to the value of a custom channel. A fader sets the value
of the channel's fader. An encoder sets the value of the channel's own encoder, else that of its fader. The slot keeps showing what it shows, e.g. the encoder of the
speaker sets the brightness. With targets, the claim follows the target the channel controls.

```toml
[controls]
1 = { encoder = { channel = "screen_left" } }
```

See [Controls and the chord](../slots.md#controls-and-the-chord).

## Simulate

Simulate in the GUI and `xtouch-daemon simulate` run the `watch` programs too, but never `set` or `run`: a move
there changes only the simulation. Until the first line of `watch`, a value is in the middle of its range. Whether a
channel with `present` is there comes from the situation you simulate, not from its watch.
