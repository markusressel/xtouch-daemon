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
| `fader` | The volume (`"volume"`). | A value: `{ set, watch, min, max, format }`. |
| `encoder` | The type's modes ([Encoders](encoders.md)). | A value: `{ set, watch, min, max, step, push, format }`. |
| `lcd` | What the type shows on the second line. | `{ watch }`: each line is the text. |
| `color` | A color name. | `{ watch }`: each line is a color name. |
| `meter` | The level of the audio (`true`), or dark (`false`). | `{ watch, min, max }`: each line is a level. |
| A button's `press`, `hold` | The type's actions ([Buttons and LEDs](leds.md)). | `{ run }`: runs to its end. |
| A button's `led` | The type's indicators. | `{ watch }`: `on`, `1`, `true`, `yes` light it, `flash` flashes it. |

Each part also takes `"homeassistant"`: Home Assistant sets it, with an entity of its own (see below).

- `set` runs with `{value}`, the newest value only; `watch` prints the value, one line per change. See
  [A value](../channels/custom.md#a-value) for `min`, `max`, `step`, `push` and `format`.
- `{value}` in `run` is the value of the fader, else of the encoder, else the volume. `{target}` is for custom
  channels with `targets`.
- A fader bound away from the volume gives the volume to the encoder. A fader has no `push`, only the encoder.
- A bound meter shows its level whatever `behavior.meters` says.
- Strings are split like a shell does, without expanding anything; a list is the program and its arguments.

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
`number.<ns>_<id>_encoder`): from the binding's `min` to its `max`, in steps of the encoder's `step` (a fader in fine
steps of the range). It has no state until the value is known; a change in Home Assistant runs `set`.

Only the channel itself has these entities. A [place](../slots.md#slots) that sets a part to `"homeassistant"` does
nothing; the log says so. Simulate has no Home Assistant: its parts look as while Home Assistant is not there.

## Simulate

Simulate runs the `watch` programs, but never `set` or `run`: a move changes only the simulation.
