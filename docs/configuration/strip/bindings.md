# Bindings

Every part of a strip does what its [channel](../channels/index.md) type says, unless the channel binds it: to Home
Assistant (`"homeassistant"`), or to programs of your own. A channel without bindings works as before. A
[custom channel](../channels/custom.md) has no defaults: every part it uses is bound. The design: [Bindings and custom
channels](../../development/design/bindings.md).

```toml
[channel.out]
type = "output"
meter = { watch = "cpu-load --watch" }        # the meter shows the CPU, the fader stays the volume
color = "homeassistant"                       # Home Assistant sets the color
```

The parts of the `output`, `input`, `apps` and `auto` channels:

| Part | Default | A program |
|---|---|---|
| `fader` | The volume (`"volume"`). | A value: `{ set, watch, min, max, step, format }`. |
| `encoder` | The type's modes ([Encoders](encoders.md)). | A value: `{ set, watch, min, max, step, push, format }`. |
| `lcd` | What the type shows on the second line. | `{ watch }`: each line is the text. |
| `color` | A color name. | `{ watch }`: each line is a color name. |
| `meter` | The level of the audio (`true`), or dark (`false`). | `{ watch, min, max }`: each line is a level. |
| A button's `press`, `hold` | The type's actions ([Buttons and LEDs](leds.md)). | `{ run }`: runs to its end. |
| A button's `led` | The type's indicators. | `{ watch }`: `on`, `1`, `true`, `yes` light it, `flash` flashes it. |

Each part also takes `"homeassistant"`: Home Assistant sets it, with an entity of its own (see below).

A place of a slot takes the words of a part only, no binding. A part that a slot shows or does whatever it shows
takes the same bindings in [`[controls]`](../slots.md#controls-and-the-chord): the fader, the encoder, the meter, the
color, the second line of the LCD, and the press and the LED of Select, Rec and Solo.

- `set` runs with the new value in `{value}`; `watch` prints the value, one line per change. See
  [A value](../channels/custom.md#a-value) for `min`, `max`, `step`, `push` and `format`.
- `{value}` in `run` is the value of the fader, else of the encoder, else the volume in percent. `{target}` is for custom
  channels with `targets`.
- A fader bound away from the volume gives the volume to the encoder. A fader has no `push`, only the encoder.
- A bound meter shows its level whatever `behavior.meters` says.
- Strings are split like a shell does, without expanding anything; a list is the program and its arguments.

## The options of a binding

A value (`fader`, `encoder`) has `set`, `watch`, `min`, `max`, `step`, `push` and `format`: see
[A value](../channels/custom.md#a-value). The `step` of a fader is that of the encoder of a custom channel (without an
encoder of its own), and of its number in Home Assistant. The other bindings have fewer options:

| Binding | For | Option | Default | Meaning |
|---|---|---|---|---|
| A watch | `lcd`, `color`, a button's `led`, `present` of a custom channel | `watch` | | A program that runs all the time and prints a line per change. The part shows the newest line. |
| A level | `meter` | `watch` | | A program that prints a number per change. |
| | | `min`, `max` | `0`, `100` | The number with the meter dark, and with the meter full. |
| A program to run | a button's `press`, `hold` | `run` | | The program and its arguments; `{value}` is the value (above). |

A `watch` takes no `{value}`; `set` needs it in an argument after the program. `min` must be below `max`, `push`
between them, and `step` above 0. `format` must show a number, e.g. `{value:.0%}`.

## Values and watches

- The fader, the ring and the LCD show a move at once. `set` runs with the newest value only: moves that come while
  it runs wait, and only the last of them runs next.
- `set` and `run` that fail, or take longer than 10 seconds, are logged as warnings.
- A `watch` runs for as long as the configuration, also while no slot shows the channel. A `watch` that ends or
  can't start runs again after 5 seconds.
- While a value is set, or its fader is under a finger, the lines of `watch` don't move it.

## Example: the brightness of a screen

The encoder of the speakers sets the brightness of a screen; the fader stays the volume. A push sets the full
brightness. `watch` prints the brightness, e.g. `0.60`, at each change.

```toml
[channel.out]
type = "output"
label = "Speaker"
encoder = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0, push = 1.0, format = "{value:.0%}" }
solo = { press = { run = "sysctrl display redshift reset -d DisplayPort-1" } }
```

A strip of its own for the screen is a [custom channel](../channels/custom.md#two-screens).

## The second line of the LCD

The second line shows, first to last: a notice (e.g. the name of a choice), the volume while it is being set, the
line of a bound `lcd`, then what the type shows. While Home Assistant is not there, a part in Home Assistant shows
`offline`.

## Home Assistant

A part in Home Assistant needs `[mqtt]`, and it gets an entity, named by the id of the channel (see
[Entities](../../guides/home-assistant.md#entities)):

| Part | Entity | Starts with |
|---|---|---|
| `fader = "homeassistant"` | `number.<ns>_<id>_fader` | 0 |
| `encoder = "homeassistant"` | `number.<ns>_<id>_encoder` | 0 |
| `lcd = "homeassistant"` | `text.<ns>_<id>_bottom` | empty |
| `color = "homeassistant"` | `select.<ns>_<id>_color` | `white` |
| `meter = "homeassistant"` | `number.<ns>_<id>_meter`, 0..100 | 0 |
| `led = "homeassistant"` | `select.<ns>_<id>_<button>_led` | `off` |

With `[mqtt]`, a fader or an encoder bound to a value is a number too (`number.<ns>_<id>_fader`,
`number.<ns>_<id>_encoder`): from the binding's `min` to its `max`, in steps of its `step`, else in fine steps of the
range. It has no state until the value is known; a change in Home Assistant runs `set`.

Only the channel itself has these entities, not the applications and devices that a place of `apps`, `auto` or
`devices` shows. A [place](../slots.md#slots) that sets a part to `"homeassistant"` does nothing; the log says so.
Simulate has no Home Assistant: its parts look as while Home Assistant is not there.

## Simulate

Simulate runs the `watch` programs, but never `set` or `run`: a move changes only the simulation.
