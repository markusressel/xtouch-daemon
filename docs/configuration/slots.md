# Channels, states and slots

What the device shows: **channels** are what a strip can control (an output, a group of applications, a person),
each strip of the device (a **slot**) has a short list of the channels it can show, and **states** (in a call,
gaming) decide which. A slot changes only when what it shows changes; the others stay as they are. The
[design](../development/design/slots/index.md) has every detail.

[`xtouch-daemon init-config`](../reference/commands.md) writes a small example. `xtouch-daemon check-config` shows a table of what each slot
shows in which states, and `xtouch-daemon why 3` why slot 3 shows what it shows now.

## Channels

A channel is something a strip controls, with the options of its type (see [Channels](channels/index.md)):

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
5 = ["people", "apps"]                      # a person of the voice chat, else the next application
```

- A slot shows the first candidate whose condition (after `if`) holds. Conditions name states and modes, with
  `and`, `or`, `not`, parentheses and `present` (the channel has something to control); see
  [Conditions](#conditions).
- `auto` is the next application that plays and has no channel of its own, and the people of the voice chat (from
  the right). `apps` and `people` are each of them alone. A slot without an entry is `auto`, and so is a stack whose
  candidates all don't hold.
- `-` is nothing: the slot is dark.
- The table form `{ show = ..., when = ..., ... }` takes options of the look at this place. The built-in pools
  (`[pool.apps]`, `[pool.auto]`, `[pool.devices]`, `[pool.people]`) take the same for all their places.

  | Candidate | Options |
  |---|---|
  | a channel | `color`, `lit_when_idle`, `rec`, `solo` (what their LEDs show), `meter`, `meter_point`, `label` |
  | `apps`, `auto` | the look (not `label`), and for the applications without a channel `encoder`, `min_volume`, `max_volume` |
  | `devices` | those of `apps`, and `select = false` |
  | `people` | `color`, `meter`, `meter_point` |

  A control for Home Assistant, or one that starts an application (`{ launch = [...] }`), is a control of the slot, not
  a place option: [`[controls]`](#controls-and-the-chord). How to start an application with Select:
  [Launching the application](channels/applications.md#launching-the-application).
- The [GUI](../guides/gui.md)'s page Slots simulates other modes and states (Simulate), in the drawing or on the device.
- `xtouch-daemon why 2` says why slot 2 shows what it shows, `xtouch-daemon why voip` where the channel is and
  why.
- When a slot shows something else, its LCD flashes the new label and why (`gaming`, `not call`) for
  `switching.banner` seconds.

Four pools are built in: `apps` (applications, see [Applications](channels/applications.md#apps-and-auto)), `people` (the
people of the voice chat, see [People](channels/people.md#where-people-sit)), `auto` (both) and `devices` (the outputs and
inputs no channel has, see [Devices](channels/devices.md#devices-without-a-channel)). `[pool.apps]` has `from`, `hold` and
`exclude`, `[pool.people]` `from`, `order` and the look of the strips of people, `[pool.auto]` the look of the
applications on its slots, `[pool.devices]` `from`, `hold`, `exclude` and the look of the strips of devices.

A pool that has no member for a slot hands it to the pool (or `-`) right below it: `["people", "apps"]` is a person,
else an application. A slot that two pools could fill goes to the one higher in its stack.

### Pools of channels

A pool of your own hands out channels: the first of its list that is present gets the first of its slots, the next
one the next, and so on. Use it for things of which only some are there at a time, e.g. several outputs:

```toml
[channel.speaker]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"

[channel.phones]
type = "output"
device = "alsa_output.usb-headset*"
tags = ["outs"]

[channel.buds]
type = "output"
device = "bluez_output.*"
tags = ["outs"]

[pool.outs]
channels = ["speaker", "#outs"]   # channel ids, or "#tag" for every channel with that tag
from = "left"                     # the side it fills its slots from (default)

[slots]
1 = "outs"
2 = "outs"
```

- A channel of the list that a slot of its own shows (`3 = "buds"`) is not handed out by the pool.
- Unlike `apps`, a pool of channels fills by its order every time: when an earlier channel comes back, the others
  move on one slot. For channels that should keep their strip, give each a slot of its own
  (`["buds if present", "auto"]`).
- A pool of channels goes above the built-in pools in a stack: `["outs", "auto"]`, not `["auto", "outs"]`.
- It has no look of its own: its channels bring theirs.

### Pools of applications and of people

`kind` makes a pool of your own hand out members instead of channels: `kind = "apps"` the applications that play and
match, `kind = "people"` listed people of the voice chat, each on a strip of its own. Use them to split what `apps` and
`people` hand out in one piece:

```toml
[pool.music]
kind = "apps"
match = ["@music"]            # parts of names or binaries, and presets, as in an `apps` channel
exclude = ["spotify-ads"]     # optional: never these, though they match
from = "left"                 # the side it fills its slots from (default)
hold = 5                      # seconds a slot keeps an application after it stopped (default)
color = "green"               # the look of its strips

[pool.friends]
kind = "people"
people = ["Alice", "Bob"]     # names in the voice chat; this is their order
from = "right"                # the default of a pool of people
talking_color = "green"

[slots]
5 = ["music", "apps"]         # a music player if one plays, else the next other application
6 = "apps"
7 = ["friends", "people"]     # Alice and Bob first, then anyone else in the call
```

| Option | `kind = "apps"` | `kind = "people"` |
|---|---|---|
| `match` | Required. | Not allowed. |
| `exclude` | Optional. | Not allowed. |
| `people` | Not allowed. | Required: names as in `person` of a channel, ignoring case. |
| `from` | `left` | `right` |
| `hold` | Seconds, default 5. | Not allowed: people stay `absent_after` seconds, as in `people`. |
| Look | `color`, `meter`, `meter_point`, `rec`, `solo`, `lit_when_idle`, `min_volume`, `max_volume`; no `pick` encoder. | `color`, `meter`, `meter_point`, `rec`, `solo`, `lit_when_idle`, `talking_color`. |

- A pool of your own takes its members first: a music player goes to `music`, not to `apps` or `auto`. An `apps`
  channel or a `person` channel that has a slot keeps its application or person.
- It takes them **only while a slot names it**, in any stack. A pool that no slot names takes nothing, so a forgotten
  `[pool.music]` can't make the players disappear from the device; `check-config` says "pool music is on no slot".
- A member that finds no slot waits in its pool: with one slot for `friends`, Bob waits and does not fall into `people`.
- Like `apps`, an application keeps its slot while it plays; a pool of people fills by the order of its list.
- Several pools share a slot as candidates: `["friends", "music", "auto"]`. A pool above `auto` or another pool wins
  a slot that both could fill; a slot a pool has no member for goes to the candidate below it.

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
`channels`, `homeassistant` (a switch in Home Assistant), or `when` (a [condition](#conditions) of other states). `delay_on`
(default 0) and `delay_off` (default 3 seconds, 10 for a mode) smooth it: the state goes on only after its sources
were on that long, and off only after they were off that long. A state with `when` has no delays by default (both
0): it follows the states it names, which have theirs already; delays you give it add to theirs. Modes are states with `mode = true`: the one with the highest `priority` whose sources are
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

## Conditions

A condition says when something applies: a candidate of a slot (after `if`, or `when` in the table form), a state
(`when`) or controls (`when`). It holds or not at any moment, and the slot follows at once.

| Part | Holds while | Example |
|---|---|---|
| a state or mode | it is on | `call`, `gaming` |
| `default` | no other mode is on | `default` |
| `present` | the channel or pool of the candidate has something to control | `browser if present` |
| `present(<channel or pool>)` | that channel or pool has something to control | `present(game)` |
| `not <part>` | the part does not hold | `not call` |
| `<part> and <part>` | both hold | `call and not gaming` |
| `<part> or <part>` | either holds | `call or present(voip)` |
| `( ... )` | what is inside holds | `(call or gaming) and present` |

- `not` binds closest, then `and`, then `or`: `not call and gaming or present` is `((not call) and gaming) or
  present`. Parentheses say otherwise.
- The words are lowercase, names are those of the file (`[state.<name>]`, `[channel.<name>]`, `[pool.<name>]`), and
  the built-in pools `apps`, `people`, `auto` and `devices`.
- A candidate without a condition always holds; below it, the others are never reached, except pools and `-` below
  a pool: they get the slots it has no member for.
- Present means it has something to control: an `apps` channel while its application plays, an `output` or `input`
  channel while one of its `devices` is there (always without `devices`), a `person` channel while the person is in
  the voice chat, a `homeassistant` channel always. A channel stays present `absent_after` seconds (3 by default)
  after that ended. `apps` is present while an application it may take plays, `people` while someone is in the
  voice chat, `auto` while either is, `devices` while a device no channel has is there, another pool while one of its channels is present.
- `present` is only for candidates of slots: a state takes channels with its `channels` source, and controls apply
  whatever the slot shows.
- `check-config` and the GUI name the mistakes: an unknown state, mode, channel or pool, a word where none fits, a
  condition that ends too early. The GUI underlines them in the field When.

```toml
[slots]
2 = ["browser if present", "auto"]                   # the browser while it plays, else the next application
7 = ["voip if call and not gaming", "auto"]          # the voice chat in a call, but not while gaming
8 = ["game if gaming or present(game)", "-"]         # the game in the mode gaming or while it plays
```

## Controls and the chord

`[controls]` claims parts of a slot, whatever it shows:

```toml
[controls]
2 = { select = { launch = ["mumble"] }, when = "not call" }    # Select starts Mumble while not in a call
5 = { select = "toggle:call", solo = "mode:gaming" }
6 = { fader = "homeassistant", id = "desk" }                    # the fader is number.xtouch_desk_fader
```

`when` takes a [condition](#conditions) of states and modes: the controls apply while it holds. Actions:
`homeassistant`, `cycle_modes`, `mode:<id>`, `toggle:<state or mode>`, or `{ launch = [...] }` (see
[Launching the application](channels/applications.md#launching-the-application)).
A fader or an [encoder](strip/encoders.md) takes `homeassistant` (a number entity there), or the value of a
[custom channel](channels/custom.md): `7 = { encoder = { channel = "screen_left" } }`. The slot keeps showing what it
shows, and the [LED](strip/leds.md) ring shows the value.

| Option of `[switching]` | Default | Meaning |
|---|---|---|
| `chord` | `[1, 8]` | The slots (from 1 on the left) whose Solo buttons, held together, cycle the modes; `[]` for no chord. `chord = { strips = [1, 8], action = "toggle:call" }` does another action. |
| `banner` | `1.5` | Seconds the LCDs show the label of a new mode, and a slot that shows something else its new label and why; `0` for none. |

## Home Assistant

With `[mqtt]`: `select.xtouch_mode`, a binary sensor per state (with `since`,
`source` and `override`), an override select per state that is no mode, an input switch per state with `homeassistant = true`,
`binary_sensor.xtouch_<channel>_shown`, and `sensor.xtouch_slot_<n>` (what the slot shows, with `label`, `kind`, `via`
and `reason`). See [Home Assistant](../guides/home-assistant.md).

Next: [Devices](channels/devices.md), [Applications](channels/applications.md) and [People](channels/people.md) say what each channel type takes; [Presets](presets.md) the `@` names.
