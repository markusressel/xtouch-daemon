# Bindings

Every part of a strip does what its [channel](../channels/index.md) type says, unless the channel binds it: to Home Assistant
(`"homeassistant"`), or to programs of your own. A channel without bindings works as before. A
[custom channel](../channels/custom.md) has no defaults: every part it uses is bound.

Status: being built. The configuration takes every binding below and checks it when the file is loaded; the fader and
the encoder bound to a value work, the other parts follow. The design: [Bindings and custom
channels](../../development/design/bindings.md).

```toml
[channel.out]
type = "output"
meter = { watch = "cpu-load --watch" }        # the meter shows the CPU, the fader stays the volume
color = "homeassistant"                       # Home Assistant sets the color
```

| Part | Default | A program |
|---|---|---|
| `fader` | The volume (`"volume"`). | A value: `{ set, watch, min, max, format }`. |
| `encoder` | The type's modes ([Encoders](encoders.md)). | A value: `{ set, watch, min, max, step, push, format }`. |
| `lcd` | What the type shows on the second line. | `{ watch }`: each line is the text. |
| `color` | A color name. | `{ watch }`: each line is a color name. |
| `meter` | The level of the audio (`true`), or dark (`false`). | `{ watch, min, max }`: each line is a level. |
| A button's `press`, `hold` | The type's actions ([Buttons and LEDs](leds.md)). | `{ run }`: runs to its end. |
| A button's `led` | The type's indicators. | `{ watch }`: `on`, `1`, `true`, `yes` light it, `flash` flashes it. |

- `set` runs with `{value}`, the newest value only; `watch` prints the value, one line per change.
- `{value}` in `run` is the value of the fader, else of the encoder. `{target}` is for custom channels with `targets`.
- A fader bound away from the volume gives the volume to the encoder. A fader has no `push`, only the encoder.
- A part in Home Assistant needs `[mqtt]`.
- Strings are split like a shell does, without expanding anything; a list is the program and its arguments.
