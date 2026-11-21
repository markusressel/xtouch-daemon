# Custom channels

A `custom` channel is a strip whose parts you bind to programs of your own, e.g. a fader that sets the brightness of
a screen. Its fader takes a value that programs set and watch; its [encoder](../strip/encoders.md) sets the same value
in fine steps (or one of its own), the [LED](../strip/leds.md) ring and the second line of the LCD show it. It works
like any other channel: a candidate in the [slots](../slots.md#slots), a member of pools.

```toml
[channel.screen_left]
type = "custom"
label = "Left"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0, format = "{value:.0%}" }
encoder = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", min = 0.1, max = 1.0, push = 1.0 }
```

A value (`fader = { ... }`, `encoder = { ... }`) takes these options; only the encoder has a `push`:

| Option | Default | Meaning |
|---|---|---|
| `set` | | The program that sets the value, then each argument; `{value}` in an argument is the new value, e.g. `0.55`. A string is split like a shell does, but nothing is expanded. |
| `watch` | none | A program that runs all the time and prints the value, one line per change. The first number of a line counts. The fader, the ring and the LCD follow it. |
| `min`, `max` | `0`, `100` | The value with the fader at the bottom and at the top, the ring empty and full. |
| `step` | `behavior.encoder_step` percent of the range | How much one step of the encoder changes the value. |
| `push` | none | The value a push of the encoder sets. Without it, a push does nothing. |
| `format` | `{value:g}` | How the LCD shows the value, in the [format of Python](https://docs.python.org/3/library/string.html#formatspec). |

The channel takes `label` (by default its id) and `color` (by default `white`). The buttons do nothing yet, the meter
stays dark, and the channel is always present.

## How the value is set

The fader, the ring and the LCD show a change at once. The program runs with the newest value only: turns and moves
that come while it runs wait for it, and only the last of them runs next. A program that fails or takes longer than 10
seconds is logged as a warning.

Without `watch` the daemon knows only the values it set. Until the first one, the ring is dark, the fader stays where
it is, and a turn starts from `push`, or else from `min`. While a value is set or the fader is under a finger, the
lines of `watch` don't move it. A `watch` that ends or can't start runs again after 5 seconds.

`watch` runs for as long as the configuration, also while no slot shows the channel. Simulate in the GUI runs the
`watch` programs too, but never `set`: a move there changes only the simulation. Until the first line of `watch`, it
shows the middle of the range.

## On another slot

`[controls]` can give the fader or the encoder of any slot to the value of a custom channel: the value of its fader,
for an encoder that of its own encoder if it has one. The slot keeps showing
what it shows, e.g. the encoder of the speaker sets the brightness:

```toml
[controls]
1 = { encoder = { channel = "screen_left" } }
```

See [Controls and the chord](../slots.md#controls-and-the-chord).

## Several screens

Two values are two channels, each with its own programs:

```toml
[channel.screen_left]
type = "custom"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", min = 0.1, max = 1.0 }

[channel.screen_right]
type = "custom"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-2 -b {value}", min = 0.1, max = 1.0 }
```
