# Bindings

Every part of a strip does what its [channel](../channels/index.md) type says, unless the channel binds it: to Home
Assistant (`"homeassistant"`), to programs of your own, or to an [entity of Home Assistant](#an-entity-of-home-assistant)
(`{ entity = "..." }`). A channel without bindings works as before. A
[custom channel](../channels/custom.md) has no defaults: every part it uses is bound. The design: [Bindings and custom
channels](../../development/design/bindings.md).

```toml
[channel.out]
type = "output"
meter = { watch = ["sh", "-c", "vmstat -n 1 | awk 'NR > 2 { print 100 - $15; fflush() }'"] }   # the meter shows the CPU load, the fader stays the volume
color = "homeassistant"                       # Home Assistant sets the color
lcd = { entity = "sensor.outside_temperature" }   # the second line shows an entity of Home Assistant
```

The parts of the `output`, `input`, `apps` and `auto` channels:

| Part | Default | A program | An entity |
|---|---|---|---|
| ![](../../images/controls/fader.png){ .xt-icon } `fader` | The volume (`"volume"`). | A value: `{ set, watch, min, max, step, format }`. | `{ entity, attribute, min, max, step, format, service, data }`: sets it. |
| ![](../../images/controls/encoder.png){ .xt-icon } `encoder` | The type's modes ([Encoders](encoders.md)). | A value: `{ set, watch, min, max, step, push, format }`. | As the fader, with `push`. |
| ![](../../images/controls/lcd.png){ .xt-icon } `lcd` | What the type shows on the second line. | `{ watch }`: each line is the text. | `{ entity, attribute }`: its state or attribute. |
| ![](../../images/controls/color.png){ .xt-icon } `color` | A color name. | `{ watch }`: each line is a color name. | `{ entity, attribute }`: its color. |
| ![](../../images/controls/meter.png){ .xt-icon } `meter` | The level of the audio (`true`), or dark (`false`). | `{ watch, min, max }`: each line is a level. | `{ entity, attribute, min, max }`: its number. |
| ![](../../images/controls/select.png){ .xt-icon } A button's `press`, `hold` | The type's actions ([Buttons and LEDs](leds.md)). | `{ run }`: runs to its end. | `{ service, entity, data }`: calls a service. |
| ![](../../images/controls/rec.png){ .xt-icon } A button's `led` | The type's indicators. | `{ watch }`: `on`, `1`, `true`, `yes` light it, `flash` flashes it. | `{ entity, attribute }`: lit while `on`, `open`, `playing`, `home`. |

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

The encoder of the speakers sets the brightness of a screen with [system-control](https://github.com/markusressel/system-control) (`sysctrl`); the fader stays the volume. A
push sets the full brightness. `watch` prints the brightness, e.g. `0.60`, at each change.

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

## An entity of Home Assistant

A part can show any entity of Home Assistant, and a fader or an encoder can set one, without an automation in
between: `meter = { entity = "sensor.cpu_temp", min = 30, max = 90 }`, `color = { entity = "light.desk" }`,
`fader = { entity = "light.desk" }`. It needs the [`[homeassistant]`](../../guides/home-assistant.md#homeassistant)
section: the address of Home Assistant and a long-lived access token. The daemon follows the entities through the
WebSocket API of Home Assistant; `[mqtt]` is not needed for them.

| Option | For | Default | Meaning |
|---|---|---|---|
| `entity` | every part | required | The entity, by its ID, e.g. `sensor.cpu_temp`: `<domain>.<name>`. |
| `attribute` | every part | the state | An attribute of the entity instead of its state, e.g. `media_title` of a `media_player`. For a value, the one of its domain (below). |
| `min`, `max` | `meter` | `0`, `100` | The number with the meter dark, and with the meter full. |
| `min`, `max` | `fader`, `encoder` | the entity's, else its domain's, else `0`, `100` | The value with the fader at the bottom and at the top. A `number` tells its own range. |
| `step`, `push`, `format` | `fader`, `encoder` | as for [a value](../channels/custom.md#a-value) | One step of the encoder, the value a push sets (the encoder only), how the LCD shows the value. |
| `service` | `fader`, `encoder` | the one of its domain | The service a move calls, with the entity as its target, e.g. `script.set_level`. |
| `data` | `fader`, `encoder` | the value of its domain | The data of `service`: `{value}` in it is the new value, e.g. `{ level = "{value}" }`. |

What a part makes of the entity:

| Part | Shows |
|---|---|
| `lcd` | The state, a number shortened to fit (`21.5`, `1013`), with its unit (`21.5°C`, `45%`, `3.2 kW`); or the attribute. |
| `color` | A light: its color (`rgb_color`, else `hs_color`), the nearest one the LCD has; `off` (dark) while it is off; white for a light without a color. Another entity: its state as a color name (an `input_select` with `red`, `blue`, ...). An attribute: a color name, or a list of red, green and blue. |
| `meter` | The number of the state (or the attribute), from `min` to `max`. |
| A button's `led` | Lit while the state is `on`, `open`, `playing` or `home` (and `1`, `true`, `yes`, as for a watch); flashing on `flash`; else dark. |
| `present` of a custom channel | Present unless the entity is `unavailable` or `unknown`, or Home Assistant does not have it. |

A fader or an encoder follows the value of the entity and sets it with a service, the newest value only, as `set`
does. These domains need no `service`:

| Domain | Value | Range | Service |
|---|---|---|---|
| `light` | `brightness` (`0` while off) | 0..255 | `light.turn_on` with `brightness` |
| `number`, `input_number` | the state | the entity's `min`..`max` | `number.set_value`, `input_number.set_value` with `value` |
| `media_player` | `volume_level` | 0..1 | `media_player.volume_set` with `volume_level` |
| `cover` | `current_position` | 0..100 | `cover.set_cover_position` with `position` |
| `fan` | `percentage` (`0` while off) | 0..100 | `fan.set_percentage` with `percentage` |

Any other entity, or another attribute, needs `service` and `data` with `{value}`. `{value}` alone is the number,
`{value}` within a text is its digits. A press or a hold calls a service with `{ service, entity, data }`. It sends
`data` as it is: `{value}` in it is an error.

```toml
[channel.lamp]
type = "custom"
label = "Lamp"
fader = { entity = "light.desk" }                         # the brightness
encoder = { entity = "light.desk", attribute = "color_temp_kelvin", service = "light.turn_on", data = { color_temp_kelvin = "{value}" }, min = 2700, max = 6500, step = 100 }
color = { entity = "light.desk" }
select = { press = { service = "light.toggle", entity = "light.desk" }, led = { entity = "light.desk" } }
present = { entity = "light.desk" }                       # dark while the lamp is unavailable

[channel.out]
type = "output"
meter = { entity = "sensor.cpu_temperature", min = 30, max = 90 }
solo = { press = { service = "scene.turn_on", entity = "scene.movie" } }
```

- While the daemon is not connected to Home Assistant, the entities are not known: the LCD shows nothing, the meter
  rests, an LED is dark, a color stays, a value is not known. It connects again by itself.
- An entity that Home Assistant does not have is a warning in the log, once per connection, not an error of the
  file: it may come later.
- A service that fails (e.g. an entity that is unavailable) is a warning in the log. The fader or the encoder goes
  back to the value of the entity. After a call that works, it stays where you put it until the entity reports.

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
`devices` shows. A [place](../slots.md#places) that sets a part to `"homeassistant"` does nothing; the log says so.
Simulate has no Home Assistant: its parts look as while Home Assistant is not there. A fader or an encoder bound to an
entity has no number of its own: the entity is already in Home Assistant.

## Simulate

Simulate runs the `watch` programs, but never `set` or `run`: a move changes only the simulation. It shows the
entities of Home Assistant while the daemon is connected, but calls no services.
