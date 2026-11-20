# Design: command channels

Status: proposed. It builds on the command controls of `[controls]` (see [Commands](../../configuration/slots.md#commands)).

The idea: a channel type `command`, whose strip is driven by programs of your own. Its fader and encoder set a value,
its buttons run programs, its LEDs, LCD and meter show what programs print. It is not about screens: a command can be
anything, e.g. the brightness of a screen, the fan speed of a PC or the volume of a player that has no stream.

A command channel is a channel like the others: a candidate in `[slots]`, a member of pools, a subject of conditions
(`present(screen_left)`), with a form in the GUI.

## Why a channel

The command controls of `[controls]` claim a fader or an encoder of a slot, over whatever the slot shows. That is
right for "the brightness on the encoder of my speaker strip". It is not enough for a strip of its own:

- A claim can't be a candidate of a slot, so it can't take a slot only while it matters.
- It can't be in a pool, and it has no presence.
- It has no label on the LCD, no meter, and no LEDs of its own.

Adding these to `[controls]` one by one would make it a second model of a strip. A channel type has them all already.

## A channel

```toml
[channel.screen_left]
type = "command"
label = "Left"

[channel.screen_left.value]
set = "sysctrl display redshift brightness -d DisplayPort-1 -b {value}"
watch = "sysctrl display redshift brightness -d DisplayPort-1 --watch"
range = [0.1, 1.0]
push = 1.0
format = "{value:.0%}"   # 0.55 is 55% on the LCD

[channel.screen_left.select]
press = { run = ["sysctrl", "display", "redshift", "reset", "-d", "DisplayPort-1"] }
```

| Part | Does | By default |
|---|---|---|
| `value` | The value of the channel: `set`, `watch`, `range`, `step`, `push`, as for a command control. | Needed. |
| Fader | Sets `value` over `range`. | On. |
| Encoder | Sets `value` in fine steps (`step`), a push sets `push`, the LED ring shows it. `encoder = { ... }` gives it a value of its own (e.g. the color temperature next to the brightness). | `value`. |
| LCD | The first line: `label`. The second: `value` with `format`, or `lcd = { watch = [...] }` for text of its own. | `label`, the value. |
| Buttons | Select, Rec, Solo and Mute take actions as on other channels, and `{ run = [...] }`. `{value}` in `run` is the value. | Nothing. |
| LEDs | `led = { watch = [...] }`: a line `on`, `1`, `true` or `yes` lights it, `flash` flashes it, anything else turns it off. | Off. |
| Meter | `meter = { watch = [...], range = [...] }`: each line is a level; the device lets the meter fall in between. | Dark. |
| Presence | `present = { watch = [...] }`: a line with text makes the channel present, an empty line absent. | Always present. |
| Color | `color` as on other channels, or `color = { watch = [...] }`: each line is a color name (`red`, `off`, ...). A line that is no color keeps the color. | `white`. |

`run` is new: it runs a short program and waits for its end, like `set`. It differs from `launch`, which starts an
application detached and lights the LED while it runs. `run` could be an action of the buttons of `[controls]` and of
other channels too.

A command channel has no Mute of its own: Mute is a button like the others. The buttons of `[controls]` still claim
the buttons of its slot.

## Several targets

The same programs often act on several things: two screens, three fans. There are three ways, and all of them work.

### One channel each

Two channels, two strips. Nothing new: each has its own commands.

```toml
[channel.screen_left]
type = "command"
value = { set = "sysctrl ... -d DisplayPort-1 -b {value}", range = [0.1, 1.0] }

[channel.screen_right]
type = "command"
value = { set = "sysctrl ... -d DisplayPort-2 -b {value}", range = [0.1, 1.0] }
```

### One channel, one target at a time

`targets` names what the programs act on; each target sets placeholders for the commands. The strip controls one
target at a time and the LCD shows its name. `next` (an action of Select, as on output strips with `device = [...]`)
switches to the next target. Every target has its own value: the `watch` of each runs all the time, so the fader and
the ring show the right value at once.

```toml
[channel.screens]
type = "command"
label = "Screens"
targets = { Left = { display = "DisplayPort-1" }, Right = { display = "DisplayPort-2" } }
select = { press = "next" }

[channel.screens.value]
set = "sysctrl display redshift brightness -d {display} -b {value}"
watch = "sysctrl display redshift brightness -d {display} --watch"
range = [0.1, 1.0]
```

### One channel, all targets together

`together = true`: a move sets the same value on every target, `set` runs once per target. The strip shows the value
of the first target.

```toml
[channel.screens]
type = "command"
targets = { Left = { display = "DisplayPort-1" }, Right = { display = "DisplayPort-2" } }
together = true
```

A target name is what the LCD shows, so it fits 7 characters. A placeholder that no target sets is an error when the
file is loaded, so is a target that misses one the commands use.

## Slots, pools and conditions

A command channel takes part like any channel:

- **Slots**: `5 = ["screens if gaming", "auto"]`.
- **Pools**: `[pool.screens] channels = ["screen_left", "screen_right"]` hands out those present, e.g. only the
  screens that are on.
- **Conditions**: `present(screen_left)` is true while its `present` watch says so. A state can be on while a channel
  is present (`channels = ["screen_left"]`).
- **Absent**: an absent command channel acts like an absent device: a pool skips it, a slot that keeps it shows it
  dark.

## In the daemon

- A `CommandStrip` controller, built on the `CommandLink` of the command controls (`strips/command.py`). The
  programs run with `system.commands`, which the tests replace with `FakeCommands`.
- The `watch` programs run for as long as the configuration, not only while a slot shows the channel. A strip that
  comes on a slot shows the current value at once.
- Simulate in the GUI runs the `watch` programs, so it shows real values, colors and presence. It never runs `set`
  or `run`: a move in Simulate changes the value of the simulation only. Until the first line of a `watch`, its
  strips show the middle of `range`, so the preview is not dark. A `Commands` that runs only watches replaces today's
  `NoCommands`.
- With `[mqtt]` the value is `number.<ns>_<id>_value` in Home Assistant, in `range`. A change there runs `set`, as a
  move of the fader does; the entity follows `watch` and the hands. With `targets`, the number is the value of the
  target shown (with `together`, of all of them).
- `xtouch-daemon check-config` lists the commands of every channel, with the placeholders filled in.

## The parts in order

1. `type = "command"` with `value`, the fader, the encoder and the LCD, one target.
2. `{ run = [...] }` for buttons, and `led = { watch = [...] }`.
3. `present`.
4. `targets`, `next` and `together`.
5. `meter` and `color`.
6. The number entity in Home Assistant.
7. `[controls]`: `encoder = { channel = "screen_left" }` sets the value of a channel from any slot. It replaces
   `{ command = { ... } }` there, or both stay.

## Decisions

- The value is a number entity in Home Assistant, with `[mqtt]`.
- The LEDs take `on`, `1`, `true`, `yes` and `flash`; anything else is off.
- `color` can follow a `watch`.
- Simulate runs the `watch` programs, never `set` or `run`.
