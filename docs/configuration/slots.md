# Channels, states and slots

What the device shows: **channels** are what a strip can control (an output, a group of applications, a person),
each strip of the device (a **slot**) has a short list of the channels it can show, and **states** (in a call,
gaming) decide which. A slot changes only when what it shows changes; the others stay as they are. The
[design](../design/channels-states-slots.md) has every detail.

`xtouch-daemon init-config` writes a small example. `xtouch-daemon check-config` shows a table of what each slot
shows in which states.

## Channels

A channel is something a strip controls, with the options of its type (see [Channels](strips.md)):

```toml
[channel.out]
type = "output"             # or "input": a device, one of several (choices), or the default one
label = "Speaker"

[channel.voip]
type = "apps"               # the streams of a group of applications
match = ["@voip"]
label = "VoIP"

[channel.ann]
type = "person"             # someone of the voice chat, see People
person = ["Ann", "ann-phone"]

[channel.lamp]
type = "homeassistant"      # a strip of Home Assistant automations (needs [mqtt])
```

The id (`out`, `voip`) names the channel in slots, conditions and the entities in Home Assistant.

## Slots

```toml
[slots]
1 = "out"                                   # always the output
2 = ["voip if call", "auto"]                # the voice chat in a call, else the next application
3 = ["game if gaming", "-"]                 # the game in the mode gaming, else dark
4 = [{ show = "auto", color = "blue" }]     # options of the place
```

- A slot shows the first candidate whose condition (after `if`) holds. Conditions name states and modes, with
  `and`, `or`, `not`, parentheses and `present` (the channel has something to control).
- `auto` is the next application that plays and has no channel of its own, and the people of the voice chat (from
  the right). A slot without an entry is `auto`, and so is a stack whose candidates all don't hold.
- `-` is nothing: the slot is dark.
- The table form `{ show = ..., when = ..., ... }` takes options of the look at this place (`label`, `color`,
  `lit_when_idle`, `rec`, `solo`, `meter`, `meter_point`); on `auto` also `encoder`, `min_volume` and `max_volume`.
- The GUI's page Device simulates other modes and states (Simulate) and lists every combination that shows
  something else (Grid), like the table of `check-config`.
- `xtouch-daemon why 2` says why slot 2 shows what it shows, `xtouch-daemon why voip` where the channel is and
  why.
- When a slot shows something else, its LCD flashes the new label and why (`gaming`, `not call`) for
  `switching.banner` seconds.

`auto` and the people are on the [People](people.md) page as well. `[pool.auto]` has `hold` (seconds a slot keeps an
application after it stopped playing, 5 by default) and `exclude` (applications it never takes, by default
`speech-dispatcher`, the voice of screen readers); `[people]` the look of the strips of people (`color`,
`talking_color`, ...).

## States and modes

```toml
[state.call]
voice_chat = true           # in a channel of the voice chat
recording = ["discord"]     # or: Discord records
delay_off = 5

[state.gaming]
mode = true                 # one mode at a time; without one, "default"
label = "Gaming"            # the banner across the LCDs
processes = ["@steam-games"]
```

A state is on while any of its sources is: `apps` (playing), `recording`, `voice_chat`, `processes`, `devices`,
`channels`, `homeassistant` (a switch in Home Assistant), or `when` (an expression of other states). `delay_on` and
`delay_off` smooth it. Modes are states with `mode = true`: the one with the highest `priority` whose sources are
on is the mode, else `default`. When the mode changes, the LCDs show its `label` across the strips for
`switching.banner` seconds.

`apps` and `processes` take parts of names, ignoring case, and [presets](presets.md). For games from Steam,
`processes = ["@steam-games"]` is on while any game runs, native or with Proton: Steam starts every game through its
`reaper` process, which is what the preset stands for. Proton games play as `<Game>.exe` (e.g. "Planet
Crafter.exe"), which `apps = ["@games"]` catches once they make a sound. Don't use `steam` (the client runs all the
time) or `.exe` in `processes` (Wine's helpers, like `explorer.exe`, run for other Windows programs too).
`ps -eo comm,args` while a game runs shows the names to use for others. Kernel threads don't count.

Every state can be overridden (`on`, `off`, `auto`) from Home Assistant, the GUI's live view or a button; the
override lasts until its sources change (`persist = true`: until it is set back). A mode picked by hand
(`xtouch-daemon mode gaming`, the [chord](#controls-and-the-chord), Home Assistant) lasts until the rules want
another one.

## Controls and the chord

`[controls]` claims parts of a slot, whatever it shows:

```toml
[controls]
2 = { select = { launch = ["mumble"] }, when = "not call" }    # Select starts Mumble while not in a call
5 = { select = "toggle:call", solo = "mode:gaming" }
6 = { fader = "homeassistant", id = "desk" }                    # the fader is number.xtouch_desk_fader
```

Actions: `homeassistant`, `cycle_modes`, `mode:<id>`, `toggle:<state or mode>`, or `{ launch = [...] }` (see
[Launching the application](applications.md#launching-the-application)).

| Option of `[switching]` | Default | Meaning |
|---|---|---|
| `chord` | `[1, 8]` | The slots (from 1 on the left) whose Solo buttons, held together, cycle the modes; `[]` for no chord. `chord = { strips = [1, 8], action = "toggle:call" }` does another action. |
| `banner` | `1.5` | Seconds the LCDs show the label of a new mode, and a slot that shows something else its new label and why; `0` for none. |

## Home Assistant

With `[mqtt]`: `select.xtouch_mode`, a binary sensor per state (with `since`,
`source` and `override`), an override select per state, an input switch per state with `homeassistant = true`,
`binary_sensor.xtouch_<channel>_shown`, and `sensor.xtouch_slot_<n>` (what the slot shows, with `label`, `kind`, `via`
and `reason`). See [Home Assistant](../home-assistant.md).
