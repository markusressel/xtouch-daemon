# Design: bindings and custom channels

Status: built (2026-11-21), not released. How to use it: [Bindings](../../configuration/strip/bindings.md) and
[Custom channels](../../configuration/channels/custom.md).

The idea: every part of a strip (the fader, the encoder, the second line of the LCD, the color, the meter, each
button and its LED) does what the channel type says, unless the channel binds it to something else: to Home
Assistant, or to programs of your own. A channel without bindings is what it is today. A `custom` channel has no
defaults at all: every part it uses is bound.

```toml
[channel.out]
type = "output"
device = "alsa_output.usb-*"
meter = { watch = "cpu-load --watch" }        # the meter shows the CPU, the fader stays the volume
color = "homeassistant"                       # select.xtouch_out_color, an automation sets it

[channel.screen_left]
type = "custom"
label = "Left"
fader = { set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}", watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch", min = 0.1, max = 1.0 }
select = { press = { run = "sysctrl display redshift reset -d DisplayPort-1" } }
```

## Why

Channel types fix what each part does. That is right most of the time, but not always: the meter of the speakers
could show the CPU, the color of a strip the state of a light, the encoder of the music the brightness of a screen.
A type per combination would not end. Some parts could already be bound: `fader = "homeassistant"`,
`encoder = "homeassistant"`, `press = "homeassistant"`. Bindings make that the rule for every part.

It stays bounded:

- The parts are fixed: the fader, the encoder with its ring, the LCD's second line, the color, the meter, Select, Rec,
  Solo (and Mute on `custom` channels) with their LEDs. The label is text.
- A part takes one of three: the default of the type (its words, e.g. `encoder = "balance"`), `"homeassistant"`, or a
  program of your own. Nothing else: no conditions, no combinations. When a part matters is the business of states
  and slots.
- Each binding is a small table of the same few options wherever it is.

## The bindings

| Part | Default | `"homeassistant"` | A program |
|---|---|---|---|
| `fader` | The volume (`"volume"`). | `number.<ns>_<id>_fader`. | A value: `{ set, watch, min, max, format }`. |
| `encoder` | The type's modes (`volume`, `balance`, `pick`, `media`). | `number.<ns>_<id>_encoder`, a push is an event. | A value: `{ set, watch, min, max, step, push, format }`. |
| `lcd` | The volume, the balance, ... | `text.<ns>_<id>_bottom`. | `{ watch }`: each line is the text. |
| `color` | A color name. | `select.<ns>_<id>_color`. | `{ watch }`: each line is a color name. |
| `meter` | The level of the audio (`true`), or dark (`false`). | `number.<ns>_<id>_meter`, 0..100. | `{ watch, min, max }`: each line is a level. |
| A button's `press`, `hold` | The type's actions. | An event (as today). | `{ run }`: runs and waits for its end. |
| A button's `led` | The type's indicators. | `select.<ns>_<id>_<button>_led`. | `{ watch }`: `on`, `1`, `true`, `yes` light it, `flash` flashes it. |

- A **value** (`set`, `watch`, `min`, `max`, `step`, `push`, `format`): `set` runs with `{value}`, the newest only;
  `watch` prints the value, one line per change, and the part follows it. The LCD shows a value the fader or encoder
  sets in `format` while it changes (2 seconds), as it shows the balance today.
- A **watch** runs for as long as the configuration, also while no slot shows the channel, and runs again 5 seconds
  after it ends.
- **`run`** runs a short program and waits for its end, like `set`; `{value}` in it is the value of the fader (or of
  the encoder, without one). It differs from `launch`, which starts an application detached.
- Strings are split like a shell does, without expanding anything; a list is the program and its arguments.

### Where parts meet

- A fader bound away from the volume gives the volume to the encoder, as `fader = "homeassistant"` does today.
- On an audio channel Mute mutes; it is not a part to bind. A `custom` channel's Mute is a button like the others.
- An encoder without its own binding on a `custom` channel sets the fader's value, by its `step`.

## Custom channels

`type = "custom"` replaces the `command` type. Its strip has no defaults: an unbound part is dark and does nothing.
It takes the bindings above, `label`, and:

- `present = { watch }`: a line with text makes the channel present, an empty line absent. Without it, always
  present. An absent custom channel acts like an absent device: a pool skips it, a slot that keeps it shows it dark.
- `targets = [{ name = "Left", value = "DisplayPort-1" }, ...]`: `{target}` in its programs is the `value` of a
  target. The strip controls one target at a time, its `name` on the LCD; Select's `next` switches. Each target has
  its own values and watches.
- `together = true`: a move sets every target, the strip shows the first one.

```toml
[channel.screens]
type = "custom"
label = "Screens"
targets = [{ name = "Left", value = "DisplayPort-1" }, { name = "Right", value = "DisplayPort-2" }]
fader = { set = "sysctrl display redshift brightness -d {target} -b {value}", watch = "sysctrl display redshift brightness -d {target} --watch", min = 0.1, max = 1.0 }
select = { press = "next" }
```

The `homeassistant` type stays: a strip whose every part is in Home Assistant, as today. A `custom` channel with every
part `"homeassistant"` would be the same, but longer to write.

## `[controls]`

A part of `[controls]` takes the same bindings: `7 = { encoder = { set = "...", watch = "..." } }`, `"homeassistant"`,
or `{ channel = "screen_left" }`, which shares the value of a channel's fader (or encoder) with the slot. Buttons take
`{ run }` too.

`[controls]` claims what a slot shows as well, whatever the slot shows: `meter` (`"homeassistant"` or
`{ watch, min, max }`), `color` (a color, `"homeassistant"` or `{ watch }`), `lcd` (`"homeassistant"` or `{ watch }`),
and the LED of a button: `select = { press = <action>, led = <LED> }`, either key left out. `led` alone claims the
LED only, and the press stays with what the slot shows; `press` alone is the action as before, its LED shows what it
does. `led` takes `off`, `press`, `"homeassistant"` or `{ watch }`. The entities are those of a channel, by the `id` of
the controls or `slot_<n>`: `number.<ns>_<id>_meter`, `select.<ns>_<id>_color`, `text.<ns>_<id>_bottom`,
`select.<ns>_<id>_<button>_led`.

In the runtime, a claim has two sets: `taken`, the controls whose events go to it (the desk routes them), and
`shown`, the parts it shows instead of the strip of the slot (`VirtualStrip.mask()` keeps them from the device, and
gives them back when the claim goes). The desk shows the level of a claimed meter and stops the capture of the strip
below it. The watches of a claim run for as long as the configuration, like those of a channel.

Places stay words only: a part could otherwise be bound at three levels (channel, place, slot), which is hard to
follow. Bindings of a slot go through `[controls]`.

## Home Assistant

The entities of the bound parts are those of the `homeassistant` type, by the channel's id: `number.<ns>_<id>_meter`,
`select.<ns>_<id>_color`, `text.<ns>_<id>_bottom`, `select.<ns>_<id>_<button>_led`. With `[mqtt]` only, checked when
the file is loaded. With `[mqtt]`, the value of a fader or an encoder bound to a program is a number there too
(`number.<ns>_<id>_fader`, from `min` to `max`): a change in Home Assistant runs `set`, as a move does.

Reading any entity of Home Assistant (`meter = { entity = "sensor.cpu_temp" }`) needs its API: in TODO.md.

## The GUI

A part that can be bound has one field: the default of the type, Home Assistant, or a program. Its options show only
when a program is chosen. A channel without bindings looks as it does today.

## Simulate

Simulate runs the `watch` programs, so it shows real values, colors, texts and presence. It never runs `set` or
`run`: a move there changes the simulation only. Until the first line of a watch, a value shows the middle of its
range.

## Decisions

- No compatibility: the project is at 0.x. `type = "command"` and its flat options (`set`, `watch`, `min`, ... on the
  channel) go; the fader of a `custom` channel takes them as a binding. `{ command = { ... } }` of `[controls]` went
  before.
- Bindings are small tables, not flat options with prefixes (`meter_watch`): the GUI gets one field for them.
- The LEDs take `on`, `1`, `true`, `yes` and `flash`; anything else is off.
- Simulate runs the watches, never `set` or `run`.
- With `[mqtt]`, the value of a program is a number in Home Assistant too.
- A fader bound away from the volume gives the volume to the encoder, whatever it is bound to. A fader has no
  `push`: that is an error, on a channel and in `[controls]`.
- `{value}` in `run` is the value of the fader, else of the encoder, else the volume in percent. While it is not
  known, the program does not run and the log says so. In `[controls]`, `{value}` needs a fader or an encoder there
  that is a value or a `{ channel }`.
- Two faders on one value (a custom channel and a `[controls]` claim of it) each hold their own touch: one that lets
  go does not release the other. A custom strip moves its touch to the new target when it switches.
- On an audio strip, `led = "press"` stays dark for a `{ run }`; on a custom strip it is lit while the program runs.
- A bound meter shows its level whatever `behavior.meters` says.
- Each part in Home Assistant has an entity of its own, named by the id of the channel. A place of a slot that sets a
  part to `"homeassistant"` does nothing and logs it: only channels have entities. The entities of pool members
  with parts in Home Assistant are not announced yet: that needs entities that change at runtime.
- Simulate has no Home Assistant: a `homeassistant` channel shows its label, its color and `offline`, and its
  controls do nothing. Whether a custom channel with `present` is there comes from the simulated situation.
