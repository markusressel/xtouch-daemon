# Design: channels, states and slots

Status: proposal (prototyping). It replaces layouts, `inherit` strips and `collapse` with concepts that are each
edited in one place. The configuration format may change freely before 0.1.0. Revision 4, after three independent
reviews, see [Review log](#review-log). The resolver and the state engine run as a prototype (`xtouch_daemon.slots`,
`xtouch-daemon simulate`), see [Prototype](#prototype); the daemon doesn't use them yet.

## Motivation

A `[[strip]]` today answers four questions at once, and the answers are spread over several mechanisms:

| Question | Today |
|---|---|
| **What** does it control? | `type` and its options (`device`, `match`, `choices`, `person`, ...). |
| **When** does it matter? | Implicitly ("has nothing to control"), `collapse`, the rules of a `[[layout]]` (`apps`, `processes`). |
| **How** is it related to other strips? | `inherit` (by layout and position), the `voip` group, nothing for "these two belong together". |
| **Where** is it on the device? | Its position in a list, shifted by `collapse`, replaced as a whole by a layout. |

That makes simple wishes hard:

- "VoIP and the Mic only during a call, else `auto` strips there" needs a group that collapses together, and extra
  `auto` strips that fill in. Neither exists.
- "The VoIP strip matters while gaming and while calling" needs it in two layouts (an `inherit` strip) and a rule
  per layout, and the two can't both be active.
- `inherit` refers to "strip 6 of the layout default": moving a strip silently changes what the reference means.
  The author's own configuration shows it: its `gaming` layout inherits strip 6, an `auto` strip, where VoIP was
  meant, and puts Browser where the Mic was, so the Mic is gone while gaming.
- `collapse` moves every strip after it: the fader under the finger changes, which hurts muscle memory.
- The GUI has to show all of it in one strip form, plus a "Layout" tab, plus global pages: it feels unintuitive.

## The model

| Concept | Answers | Edited on |
|---|---|---|
| **Channel** | What a strip controls: a device, applications, a person in the voice chat, a Home Assistant strip. | Channels page |
| **Pool** | Which one of several a strip takes: whatever plays and has no slot (`auto`), the next person in the voice chat (`people`), the next present channel of a list. | Channels page |
| **State** | When something matters: a named on/off condition, live, with a manual override. A **mode** is a state that excludes the other modes (today's layouts). | States page |
| **Slot** | Where: one of the 8 strips of the device, with a stack of candidates (channels or pools, each with a condition). | Device page |

### Names

Channels, pools and states share one namespace: an id is lower case letters, digits and `_`, unique across all
three. `auto`, `people` and `default` are built in. Reserved: `and`, `or`, `not`, `if`, `present`, `none`, `mode`,
and ids starting with `state_` or `slot_` (they would collide with the entity IDs in Home Assistant). The sigils stay
those of today: `@name` a [preset](../configuration/presets.md), `#name` a tag.

### Conditions

One expression language says "when" everywhere: in candidates (`"mic if call"`) and in composed states
(`when = "..."`).

```
expr     := or
or       := and ("or" and)*
and      := not ("and" not)*
not      := "not" not | atom
atom     := ID | "present" | "present(" ID ")" | "(" expr ")"
```

- `ID`: a state or mode; `default` is on while no other mode is.
- `present`: the candidate's own channel or pool is present; only in candidates of slots (a state takes channels
  with its source `channels`). `present(spotify)`: that channel or pool is. Presence of a pool is defined before slots are assigned (below), so conditions never depend on the result.
- The GUI shows conditions as chips that read as text: `call or gaming`.
- Errors point at the place: `slots.7[0]: "voip if cal": unknown state cal (did you mean call?)`, with a caret in
  the GUI and `check-config`.

Conditions depend only on **inputs**: states and presence. Nothing in a condition depends on what other slots show.
That is what makes the resolver deterministic and Simulate truthful.

### Channels: what a strip controls

A channel is today's strip without its place: `type` and the options of that type. The table key is its id.

```toml
[channel.out]
type = "output"
color = "cyan"

[[channel.out.choices]]
label = "Phones"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:analog-stereo+input:analog-stereo"

[[channel.out.choices]]
label = "Speaker"
device = "alsa_output.pci-0000_11_00.4.iec958-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:iec958-stereo+input:analog-stereo"
max_volume = 200

[[channel.out.choices]]
label = "Buds"
device = "bluez_output.*"

[channel.spotify]
type = "apps"
match = ["spotify"]
label = "Spotify"
tags = ["media"]

[channel.alice]
type = "person"
person = ["Alice", "alice-phone"]
label = "Mum"
```

- Types: `output`, `input`, `apps`, `homeassistant` as today, and `person` (today's `voip` strip with `person`,
  with `talking_color`, `max_volume`, `meter`, `launch`). Two `person` channels with a name in common are an error,
  as today. `auto` and the group of `voip` strips are pools; `empty` is the candidate `"-"`.
- `tags`: free-form names for grouping channels, used by pools (`#media`) and the `channels` source of states.
  They are not conditions; name them after what the channels are (`media`, `games`), not after states.
- **Presence**: whether the channel has something to control: its device is there, an application of the group has
  a stream, the person is in the voice chat; always for `homeassistant`. `absent_after` (default
  `behavior.absent_after`, 3 s; today's `collapse_hold`) delays "absent", so a reconnecting Bluetooth device does not
  flap; it is present again at once.
- `in_auto` (default `true`, `apps` channels only): whether the channel goes into the `auto` pool while it plays and
  no slot shows it (below).
- Its Home Assistant entities are named by its id (`select.xtouch_out_output`), the same wherever and whenever it
  shows, and they stay available while it is not shown. One owner per stream: the channel, wherever it is.

### Pools: one of several

A pool gives each slot that shows it one **member** that no other slot shows.

| Pool | Members, in this order |
|---|---|
| `auto` (built in) | **Whatever plays and has no slot**: `apps` channels with `in_auto` that are present and not shown (each as a whole: its label, volume, entities, as in DAW banking), and applications that play and no channel matches. In the order they started playing. A member stays one for `hold` seconds after it stopped (today's `auto_hold`). |
| `people` (built in) | People in the voice chat who have no `person` channel, in the provider's order (Mumble: who came first). Like a channel, a person stays a member `absent_after` after they left, so a reconnect moves nothing. |
| `[pool.<id>] channels = [...]` | The present channels of the list (ids, `"#tag"`) that are not shown by a candidate of their own, in the list's order. |

```toml
[pool.auto]
color = "white"
hold = 5                     # today's behavior.auto_hold
exclude = ["speech-dispatcher", "notification"]   # never these: today's behavior.ignore

[pool.people]
color = "yellow"
talking_color = "green"

[pool.media]
channels = ["#media"]
```

- The options of `[pool.auto]` and `[pool.people]` are those of today's `auto` and `voip` strips; a pool of channels
  has none (its members bring their own).
- **Presence of a pool**, for `if present`, counts its members before slots are assigned: `auto` is present while
  anything plays that is not excluded, `people` while someone without a `person` channel is in the voice chat, a pool
  of channels while one of them is present. Conditions stay independent of the result.
- **Members keep their slot** in `auto` and `people`, so applications and people don't hop around. A pool of
  channels fills **by its order** instead (the first present channel gets the first slot), which is what `collapse`
  does today: Buds coming back takes its place, the others move on.
- **Paging** (`people` only): the pool has one page, shared by every slot that shows it. Select on any of them shows
  the next people (`pg 2/3`), as the group of `voip` strips does today. On other pools Select does what it does on
  the member (makes a device the default, launches).
- **Pick** (the `pick` encoder of `auto` slots), as today: turning picks the slot's member among those without a
  slot (`2/5`); a push pins it, and it stays on the slot after it stopped playing, until the next push (`pinned`,
  `auto`). A pin beats the pool's order.

### States: when something matters

A state is a named condition that is on or off, evaluated all the time and visible everywhere: the GUI, the live
view, Home Assistant, `xtouch-daemon state`.

```toml
[state.call]
voice_chat = true           # in a channel of the voice chat with others (from the bridge)
recording = ["discord", "vesktop"]   # or: one of these records (they open a capture stream only in a call)
delay_on = 2                # on only after 2 s: a join tone is no call
delay_off = 30              # stays 30 s after: a call that drops for a moment

[state.wireless]
devices = ["bluez_output.*"]

[state.focus]
when = "not call and not gaming"

[state.night]
homeassistant = true        # Home Assistant feeds it: switch.xtouch_state_night_input
```

| Source | On while |
|---|---|
| `apps` | One of these applications has a playback stream (playing or paused). Names and presets as `match`. |
| `recording` | One of these applications has a capture stream. Not for Mumble: it keeps its capture stream open while connected, even alone; use `voice_chat`. |
| `voice_chat` | The voice chat reports that you are in a channel with at least one other person. |
| `processes` | A process of one of these names runs (polled every 2 s while any state uses it). |
| `devices` | A device (output or input) that matches is there. |
| `channels` | One of these channels is present: ids, or `"#tag"`. |
| `homeassistant` | Its input switch in Home Assistant (`switch.xtouch_state_<id>_input`) is on. |
| `when` | The expression holds. Not together with other sources: a state is either composed or has sources. |

A state with several sources is on while any of them is. Without sources it is only what its override says.
`delay_on` (default 0) and `delay_off` (default `behavior.state_delay_off`, 3 s; for modes 10 s, today's
`switching.hold`, which goes away; 0 for composed states, whose expression has the delays of what it names, so
`call` and `not call` never overlap) apply to the sources, not to the override. References between states and modes
must not form a loop; `check-config` names it.

#### Overrides

Every state has an override: `auto` (the sources decide), `on` or `off`. It is set from Home Assistant
(`select.xtouch_state_<id>`), the GUI, the command line (`xtouch-daemon state call on`) or the chord. One rule for
all states and modes:

- `on` and `off` take effect at once, past the delays; back to `auto`, the sources decide at once too.
- An override lasts **until the sources change** (an edge after their delays), then it is `auto` again. Example:
  `gaming` forced off while a game runs (to use the default mode for a moment); when the game exits, `auto` again,
  and the next game brings the mode.
- `persist = true` keeps it across edges, until it is set to `auto` by hand. States without sources have no edges,
  so their override is kept by itself.
- Overrides are kept across restarts. The first evaluation after a start is the **baseline**, not an edge: a kept
  override survives it.
- An active override shows: hatched in the GUI's state bar, `override` in Home Assistant's attributes, and in the
  banner on the LCDs when it is set and when the daemon starts.

#### Modes

Modes are states with `mode = true`. Exactly one mode is on: the one with the highest `priority` whose sources are
on (then the first in the file), else `default`. The override is one `select.xtouch_mode` with `auto` and every mode,
`xtouch-daemon mode gaming`, `mode --next`/`--previous`, `mode --auto`. `--next` and the chord cycle through
`default` and the modes in the order of the file (not through `auto`). A picked mode lasts until the rules want
another mode than before; edges that don't change what the rules want (a mode of lower priority starts) and edges of
modes with `persist` don't end it.
A mode keeps `label`, the banner across the LCDs.

```toml
[state.gaming]
mode = true
label = "Gaming"
processes = ["@steam-games"]
apps = ["@games"]
```

### Slots: where it shows

The device has 8 slots, one per physical strip, numbered 1 to 8 from the left. Each slot has a stack of
candidates, top first.

```toml
[slots]
1 = ["game if gaming", "out"]
2 = ["people if gaming and present", "browser"]
7 = ["voip if call or gaming", "auto"]
8 = "mic"                   # a single candidate: the same as ["mic"]
```

- A candidate is `"<channel or pool>"`, optionally with `" if <expression>"`, or `"-"`: deliberately nothing (the
  slot is dark, today's `empty`). A slot whose value is a string has that one candidate.
- A slot without an entry is `"auto"`. A stack whose candidates all don't hold, or lose, ends in an implicit
  `"auto"`; `"-"` at the end makes it dark instead.
- The table form `{ show = "...", when = "...", ... }` takes **options for this place**:
  - on any candidate, what it looks like here: `label`, `color`, `lit_when_idle`, `rec`, `solo`, `meter`,
    `meter_point`;
  - on a pool candidate also what a strip of today's `auto` or `voip` type has: `encoder`, `fader`, `min_volume`,
    `max_volume`, `launch`, `launch_when_running`, `talking_color`, and `id`, which names the Home Assistant entities
    of this place (with `encoder` or `fader = "homeassistant"`). A channel's entities belong to the channel, so
    these are not for channel candidates.

  ```toml
  4 = [{ show = "auto", encoder = "homeassistant", id = "desk_knob" }]
  ```

Two words keep the rules apart: a candidate **holds** while its condition is true; a slot **shows** the candidate it
gets in the end. Every candidate without a condition holds: a channel that is absent is shown dark (`off`) and keeps
its place, an empty pool is shown dark like an `auto` strip without an application. `"spotify if present"` and
`"people if present"` hold only while there is something.

#### The resolver

It decides what each slot shows from the inputs (states, presence, pool members, pins, held slots) and, for pool
members only, the previous result.

1. **Fixed slots.** A slot that is held (a finger, a button) or within its dwell time keeps what it shows; its
   channel or member is reserved, and the other slots are resolved around it.
2. **Channels by rank.** Every other slot proposes its first candidate that holds. A channel that several slots
   propose goes to the one where it is highest in the stack (its rank), ties to the leftmost slot; the others go on
   to their next candidate that holds. Repeat until nothing changes. A pool candidate always takes its slot in this
   step (pools are not contested). It ends: a slot only ever goes down its stack.
3. **Pools.** The members are computed now (the `auto` pool needs to know which channels have a slot) and handed
   out: a member of `auto` or `people` keeps the slot it had if that slot still shows the pool; pinned members go to
   their slots; the others go to the remaining slots of the pool left to right, in the pool's order (a pool of
   channels: all by its order). Members left over **wait**. A slot of a pool without a member for it is dark. The
   pools of channels go first, then `people`, then `auto`: a slot meant for a channel gets it before `auto` takes it
   as a whole. A pin of a channel that has a slot of its own now is dropped (one channel, one slot).

Pools never fall through and conditions never look at the result, so the steps run once each, in this order: the
same inputs give the same result.

`check-config` warns about candidates that can never show (an earlier one always holds), channels that no stack
has, `launch` channels that only show under conditions, and lists channels in several stacks with the slot that wins
each tie.

#### Stability

- **Batching**: changes are resolved together 100 ms after the first one (a game starts several streams and a
  process at once), so faders move once.
- **Dwell**: a slot keeps what it shows for at least 1 s before it changes again.
- **Nothing changes under a finger**: a held slot is fixed (step 1) until let go. A fader in `touchless_faders`
  counts as touched while the user moves it and half a second after, as today; the motor moving it to a new channel
  doesn't count. The buttons of the chord don't hold slots.
- **Startup**: the daemon waits for the first state of the sound server and the first process scan, evaluates the
  states without `delay_on` (the baseline), restores the overrides, and only then runs the startup sequence: the first
  picture is the right one.
- **Reload**: the previous result carries over by channel id and pool member.

#### Telling what changed

A slot that changes flashes the new label on the top line and the reason on the bottom line (`call`, `gaming`,
`absent`) for `switching.banner` seconds. A mode change shows its label across all LCDs instead (no flashes per
slot at the same time). The motor fader moves to the new volume, as with banking in a DAW. The daemon logs one line
per resolution with the changes and the reasons: `7: auto:Spotify -> voip (call: Discord records); Spotify waits`.

### Pitfalls the design makes possible

- **Launch**: a channel with `launch` can only be launched while a slot shows it. `"voip if call or gaming"` hides
  VoIP exactly when you'd press Select to start the voice chat. Keep such a channel in a stack without a condition.
  `check-config` warns.
- **Indicators**: a hidden channel's LEDs are not on the device. `mic if call` hides the Mic and its Rec LED, which
  lights while any application records (a meeting in a browser tab, OBS).
- **A voice chat outside its slots**: people in a Mumble call while no slot shows `people` are on no strip; the why
  line says so ("people: on no slot").

### Home Assistant

| Entity | What |
|---|---|
| The entities of a channel (`number.xtouch_<id>_fader`, `select.xtouch_<id>_output`, ...) | As today's strips, named by the channel id. They stay available while the channel is not shown; the buttons of a `homeassistant` channel send events only while it is shown. |
| The entities of a place (`id` of a pool candidate) | As today's `auto` strips with Home Assistant controls. |
| `binary_sensor.xtouch_<id>_shown` | Whether the channel is on a slot. |
| `sensor.xtouch_slot_<n>` | What slot n shows: a channel id, `auto:<application>`, `people:<name>`, or `none`. Attributes `label`, `kind` (`channel`, `pool`, `none`), `reason`. |
| `binary_sensor.xtouch_state_<id>` | The state. Attributes `since`, `source` (which source turned it on), `override`. |
| `select.xtouch_state_<id>` | The override: `auto`, `on`, `off`. |
| `switch.xtouch_state_<id>_input` | Only for `homeassistant = true`: what Home Assistant feeds into the state. |
| `select.xtouch_mode` | The mode override: `auto` and every mode. Replaces `select.xtouch_layout`. |

### The chord

`[switching] chord = { strips = [1, 8], action = "cycle_modes" }` (default). `action = "toggle:call"` toggles the
override of a state instead (`auto` -> the opposite of its value now -> `auto`).

## A complete example

The author's configuration in this format (today about 110 lines):

```toml
# [device], [behavior], [aliases], [mqtt] unchanged

[channel.out]
type = "output"
color = "cyan"
choices = [ ... ]   # the three choices above

[channel.browser]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "blue"

[channel.game]
type = "apps"
match = ["@games"]
label = "Game"

[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "yellow"
lit_when_idle = true
in_auto = false             # notification sounds of Discord don't take an auto slot

[channel.mic]
type = "input"
device = "alsa_input.pci-0000_11_00.4.analog-stereo"
label = "Mic"
color = "red"

[pool.people]
color = "yellow"

[state.gaming]
mode = true
label = "Gaming"
processes = ["@steam-games"]
apps = ["@games"]

[state.call]
voice_chat = true
recording = ["discord", "vesktop"]
delay_on = 2
delay_off = 30

[slots]
1 = ["game if gaming", "out"]
2 = ["people if gaming and present", "browser"]
7 = ["voip if call or gaming", "auto"]
8 = ["mic if call", "auto"]
```

What it shows, as `xtouch-daemon simulate docs/design/channels-states-slots.toml --table` prints it (the example is
[that file](channels-states-slots.toml); a test keeps this table in line with it): one row per combination of states
and presence the stacks ask about that changes something.

```
when                             1     2        3-6   7     8
default                          out   browser  auto  auto  auto
call                             out   browser  auto  voip  mic
gaming                           game  browser  auto  voip  auto
gaming and call                  game  browser  auto  voip  mic
gaming, people present           game  people   auto  voip  auto
gaming and call, people present  game  people   auto  voip  mic
```

- With Mumble, people present means `call` after 2 s: joining a channel while gaming changes slot 2 at once and
  slot 8 two seconds later, each once.
- While slot 2 shows people, Browser is in the `auto` pool: if it plays, it takes an auto slot as a whole (its
  label, volume and entities), so no stream has two owners.

## The GUI

A left rail with four pages; the header and the footer (problems, undo, save) stay as they are.

```
┌──────┬────────────────────────────────────────────────────────────────────────────────┐
│ ▣    │ call ● 21:04 ▾   gaming ○ ▾   wireless ● ▾   night ▨ on ⟲      [▷ Simulate]    │
│Device├────────────────────────────────────────────────────────────────────────────────┤
│ ≡    │  [ the live device as today: LCDs, meters, faders, buttons, 8 strips ]         │
│Chan- │ ┌─1──────────┐┌─2────────────┐┌─3──────┐ ··· ┌─7──────────────┐┌─8──────────┐ │
│nels  │ │▶ Game      ││  people      ││▶ auto  │     │▶ VoIP          ││▶ Mic       │ │
│ ◐    │ │  gaming    ││  gaming and  ││ always │     │  call or gaming││  call      │ │
│States│ │  Out       ││  present     │└────────┘     │  auto          ││  auto      │ │
│ ⚙    │ │  always    ││▶ Browser     │               │  always        ││  always    │ │
│Sett. │ │ + add      ││  always      │               │ + add          ││ + add      │ │
│      │ └────────────┘└──────────────┘               └────────────────┘└────────────┘ │
│      │ Slot 2 · Browser: people doesn't hold (gaming is off)       [Slots | Grid]     │
│      │ ┌ Candidate ─────────────────┐┌ Channel browser (also in: —) ────────────────┐ │
│      │ │ show [browser ▾] always    ││ apps · match @browsers · label Browser · ... │ │
│      │ │ + condition   place opts ▾ ││                                              │ │
│      │ └────────────────────────────┘└──────────────────────────────────────────────┘ │
└──────┴────────────────────────────────────────────────────────────────────────────────┘
```

- **Device** (the start page):
  - The **state bar** is live and read-only: each state with its value and since when. Its ▾ menu sets the
    override (`auto`, `on`, `off`), which changes the daemon; an overridden state is hatched, with ⟲ to go back to
    `auto`.
  - The **live device** stays as today (LCDs, meters, faders, the buttons), above the stacks.
  - **Simulate** is a separate mode, named so it can't be mixed up with the existing **Live preview** (which runs
    the unsaved file on the device). It draws a colored frame around the device and opens a bar of what-if inputs:
    every state, the presence of the channels and pools the stacks ask about, and how many members each pool has.
    The device then shows what the resolver would. Nothing is sent. Esc ends it.
  - Each slot is a **card** with its stack: one row per candidate with its condition as text chips (`call or
    gaming`, `always`), ▶ on the one shown. Drag and drop or Ctrl+Up/Down reorder; "+ add" or dropping a channel or
    pool adds a candidate, and its condition opens as chips right away (in Simulate, prefilled with the states turned
    on).
  - The **why line** tells for the selected slot what it shows and why not the candidates above it, from the
    resolver's trace; for a selected channel where it is and why not elsewhere (`Browser: on 2; not 8 (tie to 2)`).
    The same is `xtouch-daemon why 2` and `xtouch-daemon why browser`.
  - The **inspector** edits the candidate (condition as chips or as text, the options for this place) and its
    channel or pool in one panel; it says where else that channel is used.
  - **Grid** shows the distinct outcomes, as in the example above. Clicking a row simulates it, clicking a cell
    selects that card.
- **Channels**: channels and pools in a list with type icon, label, tags and where they are used. The inspector is
  today's strip form without place and layout. "Duplicate" replaces copy and paste of strips.
- **States**: modes first, then the other states: sources or composition, delays, live value with since when and
  which source, override, and which stacks use it.
- **Settings**: `[device]`, `[behavior]`, `[aliases]`, `[mqtt]`, `[voip]`, `[switching]`.

Undo, validation, the Live preview and the problem list stay; problems link to a slot, candidate, channel, pool or
state. The GUI keeps the form a stack has in the file (string, compact list or tables) and its comments.

## A new configuration

`init-config` writes the smallest configuration that works, and the rest as comments that teach it:

```toml
[channel.out]
type = "output"             # the default output

[channel.mic]
type = "input"              # the default input

[slots]
7 = "mic"
8 = "out"                   # the main output on the right, as in a DAW; slots 1 to 6 are auto

# [state.call]               # in a call, for slots like 6 = ["voip if call", "auto"]
# voice_chat = true          # Mumble with the plugin; for Discord: recording = ["discord"]
# delay_on = 2
# delay_off = 30
#
# [state.gaming]             # a mode: while a game from Steam runs
# mode = true
# processes = ["@steam-games"]
```

## The daemon

- `StateEngine` (new, `runtime/states.py`): evaluates the states from the playback and capture streams, the voice
  chat, the process list (polled while a state needs it), the devices, Home Assistant inputs and the overrides, with
  the delays and the baseline at the start; resolves the modes; publishes to the live view and MQTT.
- `SlotResolver` (replaces `runtime/placement.py`): the steps of [The resolver](#the-resolver) and
  [Stability](#stability). Pure: inputs and the previous result in, the 8 slots and a trace (why and why not) out.
- Channel controllers live as long as the configuration, not as long as a layout: a mode switch rebinds them to
  slots (`VirtualStrip`, as the `Flow` does today) and rebuilds nothing.
- `check-config` prints channels, pools, states with their sources, per slot its stack, the outcome table, and the
  warnings above. `list-apps` says per application which channel, pool or slot has it.

## Migration

`xtouch-daemon migrate-config` (and the GUI on opening an old file) writes the new format and reports what it did:

| Old | New |
|---|---|
| A strip | A channel and a candidate in the slot of its position. Its id: its `id`; for a strip with Home Assistant entities `strip_<position>` (so `select.xtouch_strip_1_output` keeps working), with a suggestion to rename it; else its label in lower case, else `<type>_<n>`. |
| `homeassistant` strips that share entities across layouts | One channel. |
| An `auto` strip | `auto`; its options that differ from those of the other `auto` strips become options of the place. Candidates the same as the slot's fallback are dropped. |
| A `voip` strip | Without `person`: `people`. With `person`: a `person` channel. |
| An `empty` strip | `"-"`. |
| A `[[layout]]` | A `[state.<name>] mode = true` with its rules, label and priority; each of its strips a candidate `if <name>` above the default one of that slot. |
| `meter_point` of a layout | `meter_point` on the places of its candidates. |
| An `inherit` strip | A candidate of the channel it refers to. The report names every one it resolved, so surprises (like the one in the motivation) show. |
| `collapse` on a strip | The strip stays in its slot as `"<id> if present"` above `auto`: nothing shifts any more. The report lists them and points to pools of channels for those who want filling by order. |
| `behavior.auto_hold`, `behavior.ignore` | `[pool.auto] hold`, `exclude`. |
| `behavior.collapse_hold` | `behavior.absent_after`. |
| `switching.hold` | `delay_off` of each mode. |
| `switching.chord = [1, 8]` | `chord = { strips = [1, 8], action = "cycle_modes" }`. |
| `select.xtouch_layout`, `xtouch-daemon layout` | `select.xtouch_mode`, `xtouch-daemon mode`; the old command fails with a pointer, the report names the entity for automations. |

No compatibility reading of the old format: an old file fails `check-config` with a pointer to `migrate-config`.

## Tests the design needs

The resolver and the state engine are pure, so each rule gets unit tests, among them every scenario the reviews
traced:

- the example's table, row by row, and joining Mumble while gaming (slot 2 at once, slot 8 after `delay_on`);
- a channel several stacks want at the same and at different ranks; an exhausted stack ending in `auto`; `"-"`;
- a held slot keeping a channel another slot now ranks higher; a touchless fader moved by the user and by the motor;
- pool members keeping their slots and waiting (6 applications, then a call); `pick` and pins; paging of `people`;
  a pool of channels filling by order; a hidden channel taking an `auto` slot as a whole, and `in_auto = false`;
- batching and dwell; startup as the baseline with a kept override; a reload carrying the result over;
- `delay_on` swallowing a join tone; overrides in all three values, ending at an edge, with `persist`;
- modes by priority, the mode override with `auto`, `--next` order, `default` in conditions;
- composed states, loops, reserved and duplicate names, errors with positions;
- an absent channel holding versus `if present`, `absent_after`, presence of pools.

## Prototype

Three reviews of prose found three rounds of holes, each in the parts that only existed as prose. So the resolver
and the state engine are code now, pure (no sound server, no device), in `xtouch_daemon.slots`:

| Module | What |
|---|---|
| `model` | `Scene.of()`: reads `[channel.*]`, `[pool.*]`, `[state.*]`, `[slots]` with every check above. |
| `expressions` | The conditions, with errors at their position. |
| `inputs`, `timing` | An `Observation` (applications, voice chat, processes, devices, Home Assistant), presence, the delays. |
| `states` | `StateEngine`: sources, delays, overrides, modes, composed states, the baseline. |
| `resolver` | `resolve()`: fixed slots, channels by rank, pools; the trace. |
| `simulation` | `Simulation`: all of it over time, with the dwell time and held slots. |
| `outcomes` | The distinct outcomes: the table above, `simulate --table`, the GUI's grid. |
| `recording`, `replay` | `observe` records the real system; `simulate --replay` replays it: changes, flaps, time on. |

`xtouch-daemon simulate docs/design/channels-states-slots.toml --mode gaming --state call --playing firefox` shows
the slots and why. The tests (`tests/slots/`) have the scenarios the reviews traced that the prototype covers, and
one keeps the table above in line with the example. Not in the prototype: batching (a matter of when the daemon calls
it), the touch sensors (their result is `held`), paging of `people`, reload carrying the result over, cycling
through modes (`--next`), Home Assistant and the live view, the GUI, the migration.

What building it showed:

- **An override set while a delay is pending ends with it.** `call` forced off while a join tone's `delay_on` runs:
  2 s later the sources turn on (an edge), the override ends, and the call comes anyway. That is the rule ("until the
  sources change"); whether it is what people expect needs trying on the device.
- **The grid explains rank surprises.** A test configuration with `1 = ["buds if present", "out"]` and
  `3 = ["out if video", "auto"]`: in video mode without buds, `out` goes to slot 3 (rank 1 there, 2 on slot 1), and
  slot 1 shows `auto`. Correct, but only the grid (or `check-config`'s list of shared channels) makes it visible.
- **`present` on `"-"` meant nothing**: now an error.
- **Channels of a pool without a slot don't wait**: only applications and people do; such channels are just not
  shown.
- **A multi-line inline table is no TOML 1.0**: the examples of `choices` use `[[channel.out.choices]]`.
- **The code review** (a DAW, Linux desktop and Home Assistant user, reviewing the code with counter-examples) found
  seven bugs no scenario had caught, all fixed with a test each: a held slot didn't reserve a channel it showed in
  `auto`, nor did pins check for one, so a channel could be on two slots; `auto` took a channel before the pool of
  channels meant for it; pool members had no delay (a Mumble reconnect moved a fader twice) and `hold` wasn't used;
  `persist` didn't apply to modes, and any mode edge ended a pick; replays missed flaps after long stable times.
  Also: `present` in a state's `when` is an error now, composed states have no delays of their own, `simulate`
  checks its options, and `--table` no longer shows composed states apart from what they name.

Next: replay a day of real observations (`observe`, then `simulate --replay`), a review of the code and its
scenarios, then the daemon, the format of the real configuration, the GUI and the migration.

## Review log

### First review (DAW, Linux desktop and Home Assistant user)

| Finding | Decision |
|---|---|
| `voip` was both a channel and the built-in pool. | Pools became a concept; one namespace and the pool `people`. |
| An off-delay without an on-delay: a notification sound turns `call` on for 30 s. | `delay_on`/`delay_off`; `recording` and `voice_chat` as sources. |
| "Leftmost wins" ranks by position. | Rank first, ties to the left. |
| Too many ways to say "when". | One expression language; tags only group channels; `when` is exclusive with sources. |
| Modes and states were two concepts with two syntaxes. | `mode = true` on a state; every state has an override. |
| `present` was undefined for absent channels. | An absent channel holds (dark, keeps its place); `if present` skips it. |
| A touchless fader can't protect "nothing under a finger". | It counts as touched after the user moved it. |
| No feedback when a slot swaps. | The new label plus the reason. |
| Home Assistant needs to know what shows where. | `sensor.xtouch_slot_<n>`, `binary_sensor.xtouch_<id>_shown`. |
| Long syntax. | `[channel.<id>]`, the compact slot form. |
| GUI: preview and override looked the same; no overview. | Read-only state bar with override menu, Simulate, chips, one inspector, the why line, the grid. |
| Migration breaks `strip_<n>` entities. | Kept where entities exist, with a rename suggestion. |

### Second review (DAW, Linux desktop, Home Assistant user, systems design)

| Finding | Decision |
|---|---|
| Stickiness made the result depend on history. | Channels go by rank, then position, without history; only members of `auto` and `people` keep their slots. Incumbency as a tie-breaker (proposed) would break the example the same way, so ties go to the leftmost slot. "Holds" and "shows" are separate terms. |
| Pools: circular, no order, `auto_hold` missing, no per-place options or ids. | See the third review for the final rules; `hold`; options for a place and `id`. |
| `launch` unreachable behind a condition; the Mic's Rec indicator hidden. | Pitfalls section and `check-config` warnings. |
| Paging, `person` strips, `pick`, `collapse_hold` had no home. | Paging of `people`; `type = "person"`; `pick` as today; `absent_after`. |
| Overrides vs delays, persistence, mode select without `auto`, `when` ORed with sources, loops, the chord freezing slots. | Overrides bypass delays; one persistence rule (third review); `auto` in the mode select; `when` exclusive; loops are errors; chord buttons don't hold slots. |
| Expression language. | Grammar; one namespace with reserved words; pools without a prefix; tags named after kinds; errors with positions. |
| GUI: Simulate, grid explosion, why not, cards, overridden style. | All adopted. |
| Home Assistant: feeding states, the mode select, formats, attributes. | `homeassistant = true` with an input switch; formats and attributes defined. |
| Daemon: batching, dwell, startup, reload, polling, logging, `voice_chat`. | All adopted. |
| Migration notes, deliberately empty slots. | Adopted; `"-"`. |

### Third review (the same profile, with hand traces of the example)

| Finding | Decision |
|---|---|
| **Blocker**: pools and fall-through were circular; the steps didn't say how they iterate. | Pools always hold (like channels); `if present` with pool presence counted before assignment; conditions depend only on inputs; the steps run once each, in order. |
| **Blocker**: an exhausted stack and a held slot were undefined; motor moves of touchless faders. | An implicit trailing `auto` (`"-"` for dark); held and dwelling slots are fixed inputs whose channel is reserved; motor moves don't count. |
| **Blocker**: the example's table showed a scene that barely exists (people present means `call` with Mumble) and slot 8 changed twice. | The example asks `people if gaming and present` and drops Browser from slot 8; the table has presence rows and the Discord case. |
| **Blocker**: a hidden channel's streams in `auto` had two owners. | `auto` hands out whatever plays and has no slot, hidden `apps` channels as a whole; `in_auto = false` opts out. |
| **Blocker**: four contradictions (`meter_point`, `buds` as state and channel, `switching.hold`, the noisy slot 4). | `meter_point` on channels and places; the state is `wireless`; `switching.hold` goes; slot 4 removed from the example. |
| Options for a place leaked entity ownership; options of today's `auto` strips missing. | Look options on any candidate; control options and `id` on pool candidates only; the missing ones added. |
| Pools of channels: shown twice, priority inverted, `collapse` migration too broad, Select. | Members exclude channels with a slot; pools of channels fill by order; `collapse` migrates to `if present` in place; Select pages only on `people`. |
| Three persistence rules; startup as an edge. | One rule; overrides are kept across restarts; startup is the baseline. |
| Entity ID collisions; shared `homeassistant` strips in migration. | Reserved ids; one channel for shared entities. |
| `pick` changed meaning. | As today. |
| Coverage: chord syntax, `mode --next`, the CLI, `person` name overlap, `ignore` vs `exclude`, `auto_hold`, the live device in the GUI, Mumble outside its slots. | All adopted. |
| Minor: banner and flashes, chip text, the presets link, cycle order, why for channels. | All adopted. |
| Newcomer configuration and `init-config`. | [A new configuration](#a-new-configuration). |
