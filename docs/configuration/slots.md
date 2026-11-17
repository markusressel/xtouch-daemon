# Channels, states and slots

The successor of strips and layouts (see the [design](../design/channels-states-slots.md) for every detail). Instead
of whole sets of strips to switch between, each strip of the device (a **slot**) has a short list of what it can
show, and **states** (in a call, gaming) decide which. A slot changes only when what it shows changes; the others
stay as they are.

`xtouch-daemon init-config` writes a small example; `xtouch-daemon migrate-config` writes a file with strips and
layouts in this format (see [Migrating](#migrating)). `xtouch-daemon check-config` shows a table of what each slot
shows in which states.

## Channels

A channel is something a strip controls, with the options of the strip types of today:

```toml
[channel.out]
type = "output"             # or "input": a device, one of several (choices), or the default one
label = "Speaker"

[channel.voip]
type = "apps"               # the streams of a group of applications
match = ["@voip"]
label = "VoIP"

[channel.ann]
type = "person"             # someone of the voice chat
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
- When a slot shows something else, its LCD flashes the new label and why (`gaming`, `not call`) for
  `switching.banner` seconds.

`[pool.auto]` has `hold` (seconds a slot keeps an application after it stopped playing) and `exclude` (applications
it never takes); `[people]` the look of the strips of people (`color`, `talking_color`, ...).

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
on is the mode.

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

Actions: `homeassistant`, `cycle_modes`, `mode:<id>`, `toggle:<state or mode>`, or `{ launch = [...] }`. The Solo
buttons of `switching.chord` pressed together cycle the modes, or do another action:
`chord = { strips = [1, 8], action = "toggle:call" }`.

## Home Assistant

With `[mqtt]`: `select.xtouch_mode` (instead of `select.xtouch_layout`), a binary sensor per state (with `since`,
`source` and `override`), an override select per state, an input switch per state with `homeassistant = true`,
`binary_sensor.xtouch_<channel>_shown`, and `sensor.xtouch_slot_<n>` (what the slot shows, with `label`, `kind`, `via`
and `reason`). See [Home Assistant](../home-assistant.md).

## Migrating

```shell
xtouch-daemon migrate-config             # writes config.slots.toml next to config.toml
xtouch-daemon migrate-config --in-place  # replaces config.toml, keeps the old one as config.layouts.toml
```

Each strip becomes a channel and a candidate on the slot of its place, each layout a mode, and the strips of a layout
candidates `if <layout>` above those of the default one. `auto` and `empty` strips become `auto` and `-`, `voip`
strips without `person` the people of `auto` (their look goes to `[people]`), `launch` and Home Assistant on `auto`
strips `[controls]`. A strip with `collapse` stays on its slot while present (`"<id> if present"`, then `auto`):
nothing shifts any more. The command lists what needs a look: renamed entities, ids named after entities, resolved
`inherit` strips, strips without a slot.
