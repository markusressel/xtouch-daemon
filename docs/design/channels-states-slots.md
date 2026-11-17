# Design: channels, states and slots

Status: decided, being built. It replaces strips, layouts, `inherit` strips and `collapse` with concepts that are
each edited in one place; the old format goes (see [Decisions after the live test](#decisions-after-the-live-test)).
The configuration format may change freely before 0.1.0. Revision 5, after three reviews of the design and a live test
of a prototype on the device, see [Review log](#review-log). The resolver and the state engine run in
`xtouch_daemon.slots` and `xtouch-daemon simulate`; the daemon runs them as a prototype, see [Prototype](#prototype).

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
| **Pool** | Which one of several a strip takes: whatever plays and has no slot (`auto`), the next present channel of a list. | Channels page |
| **People** | The people in the voice chat: the pool `people`, and with the applications the pool `auto` (see [people-slots.md](people-slots.md)). | Channels page (look, `from` and `order`); the learned order is live there |
| **Controls** | What a fader, encoder or button of a slot does whatever the slot shows (a Home Assistant knob, starting Mumble). | Device page |
| **State** | When something matters: a named on/off condition, live, with a manual override. A **mode** is a state that excludes the other modes (today's layouts). | States page |
| **Slot** | Where: one of the 8 strips of the device, with a stack of candidates (channels or pools, each with a condition). | Device page |

### Names

Channels, pools, states and the `id`s of controls share one namespace: an id is lower case letters, digits and `_`,
unique across all four (a control `id` names Home Assistant entities like a channel id does). `auto`, `people` and
`default` are built in. Reserved: `and`, `or`, `not`, `if`, `present`, `none`, `mode`,
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
- `in_pool` (default `true`, `apps` and `person` channels): whether the channel goes into the pools `apps` and `auto`
  (a `person` channel: `people` and `auto`) while it is present and no slot shows it (below).
- Its Home Assistant entities are named by its id (`select.xtouch_out_output`), the same wherever and whenever it
  shows, and they stay available while it is not shown. One owner per stream: the channel, wherever it is.

### Pools: one of several

A pool gives each slot that shows it one **member** that no other slot shows.

| Pool | Members, in this order |
|---|---|
| `apps` (built in) | **Whatever plays and has no slot**: `apps` channels with `in_pool` that are present and not shown (each as a whole: its label, volume, entities, as in DAW banking), and applications that play and no channel matches. In the order they started playing. A member stays one for `hold` seconds after it stopped (today's `auto_hold`). |
| `people` (built in) | The people in the voice chat, see [People](#people). |
| `auto` (built in) | Both, sharing its slots; the catch-all. |
| `[pool.<id>] channels = [...]` | The present channels of the list (ids, `"#tag"`) that are not shown by a candidate of their own, in the list's order. |

```toml
[pool.auto]
color = "white"
hold = 5                     # today's behavior.auto_hold
exclude = ["speech-dispatcher", "notification"]   # never these: today's behavior.ignore

[pool.media]
channels = ["#media"]
```

- The options of `[pool.auto]` are those of today's `auto` strips; a pool of channels has none (its members bring
  their own).
- **Presence of a pool**, for `if present`, counts its members before slots are assigned: `auto` is present while
  anything plays that is not excluded, or anyone is in the voice chat (people take its slots; counted before the
  slots are assigned, so also someone whose `person` channel has a slot of its own); a pool of channels while one of
  them is present. Conditions stay independent of the result.
- **Members keep their slot** in `auto`, so applications don't hop around (people keep their order instead). A pool of
  channels fills **by its order** instead (the first present channel gets the first slot), which is what `collapse`
  does today: Buds coming back takes its place, the others move on.
- Select does what it does on the member (makes a device the default, launches).
- **Pick** (the `pick` encoder of `auto` slots), as today: turning picks the slot's member among the applications
  without a slot (`2/5`; people are not picked); a push pins it, and it stays on the slot after it stopped playing,
  until the next push (`pinned`, `auto`). A pin beats the pool's order, and people don't take a pinned slot. The
  resolver keeps the pins: the encoder only asks for one.

### People

Decided again on 2026-11-17, see [people-slots.md](people-slots.md): `people` is a built-in pool and a candidate,
`apps` the applications alone, and `auto` both, sharing its slots (people first, each from its side). A pool hands a
slot it has no member for to the pool or `-` right below it (`["people", "apps"]`), and a slot two pools could fill
goes to the one higher in its stack. `[pool.people]` replaces `[people]` (`from`, `order`, the look), `in_pool`
replaces `in_auto`, `hold` and `exclude` are options of `[pool.apps]`. What stays from below:

- The members: everyone in the voice chat who has no `person` channel, and the `person` channels (with `in_pool`,
  default `true`) that are present and have no slot of their own, each as itself (its label, look and entities).
  Like a channel, a person stays a member `absent_after` after they left, so a reconnect moves nothing.
- They sit **in their order**, for muscle memory of who sits where: `order` (names, or ids of `person` channels),
  then the others in the order they were first seen (kept 30 days, across restarts, in
  `~/.local/state/xtouch-daemon/people.json`). Slots where they are the first candidate go first, then the others,
  each from their side: no block (see [people-slots.md](people-slots.md#not-a-block)). Someone earlier in the order
  who comes moves those after them one slot on; no slot is kept empty for someone who is away.
- People don't take a pinned slot. More people than slots wait; there is no paging. Controls of a slot
  ([Controls](#controls)) don't keep them out.
- Every configuration has the voice chat's provider (`[voip]` with its defaults if the file has none), and its
  socket costs nothing while no voice chat connects.
- Members are typed: an application, a channel or a person, never told apart by their names (someone called
  `browser` is no channel). People are told apart by the voice chat's id of the participant (step 4); `order` and the
  learned order go by name.

### States: when something matters

A state is a named condition that is on or off, evaluated all the time and visible everywhere: the GUI, the live
view, Home Assistant, `xtouch-daemon state`.

```toml
[state.call]
voice_chat = true           # in a channel of the voice chat, also alone (from the bridge)
recording = ["discord", "vesktop"]   # or: one of these records (they open a capture stream only in a call)
delay_off = 5               # stays 5 s after: a reconnect, not much longer

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
| `voice_chat` | The voice chat reports that you are in a channel, also alone: joining one says you mean to talk (the mic shows before anyone comes, and the `people` pool covers who comes). |
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
1 = "out"                   # a single candidate: the same as ["out"]
2 = "browser"
3 = ["game if gaming", "auto"]
7 = ["voip if call", "auto"]
8 = ["mic if call", "auto"]
```

- A candidate is `"<channel or pool>"`, optionally with `" if <expression>"`, or
  `"-"`: deliberately nothing (the slot is dark, today's `empty`). A slot whose value is a string has that one
  candidate.
- A slot without an entry is `"auto"`. A stack whose candidates all don't hold, or lose, ends in an implicit
  `"auto"`; `"-"` at the end makes it dark instead.
- The table form `{ show = "...", when = "...", ... }` takes **options for this place**:
  - on any candidate, what it looks like here: `label`, `color`, `lit_when_idle`, `rec`, `solo`, `meter`,
    `meter_point`;
  - on an `auto` candidate also what acts on an application without a channel: `encoder` (`pick`, `media`,
    `volume`, `balance`), `min_volume`, `max_volume`.
  - These apply to the applications without a channel the place shows. A channel it shows as a member (an `apps`
    channel without a slot) looks and works as the channel; the pool's look only fills in what the channel leaves
    open. People look as `[pool.people]` says. What a control does whatever the slot shows (Home Assistant, `launch`)
    is in `[controls]`.

  ```toml
  4 = [{ show = "auto", encoder = "pick" }]
  ```

Two words keep the rules apart: a candidate **holds** while its condition is true; a slot **shows** the candidate it
gets in the end. Every candidate without a condition holds: a channel that is absent is shown dark (`off`) and keeps
its place, an empty pool is shown dark like an `auto` strip without an application. `"spotify if present"` and
`"auto if present"` hold only while there is something.

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
   out: the people take the slots of `auto` from the right, in their order (not pinned ones, see [People](#people));
   pinned members go to their slots; a member of `auto` keeps the slot it had if that slot still shows the pool and
   no person took it; the others go to the remaining slots of the pool left to right, in the pool's order (a pool of
   channels: all by its order). Members left over **wait**. A slot of a pool without a member for it is dark. The
   pools of channels go first, then the people take their share of the slots of `auto`, then `auto` hands out its
   applications: a slot meant for a channel gets it before `auto` takes it as a whole. A pin of a channel that has
   a slot of its own now is dropped (one channel, one slot).

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

### Controls

What a fader, encoder or button of a slot does whatever the slot shows: actions that belong to the place on the
device, not to a channel.

```toml
[controls]
4 = { encoder = "homeassistant" }                        # number.xtouch_slot_4_encoder and push events
7 = { select = { launch = ["mumble", "mumble://..."] }, when = "not call" }
1 = { solo = "toggle:night", rec = "homeassistant" }
2 = { fader = "homeassistant", id = "desk_fader" }       # number.xtouch_desk_fader_fader
3 = [                                                    # by mode: the first whose when holds
    { encoder = "homeassistant", id = "strip_3", when = "gaming" },
    { select = { launch = ["obs"] } },
]
```

- A slot's controls can claim `fader`, `encoder` (turn and push), `select`, `rec` and `solo`; not Mute, which stays
  with what the slot shows.
- Actions: `"homeassistant"` (a number for the fader or encoder, events for the buttons, and a select for their LED),
  `{ launch = [...], launch_when_running = ... }`, and the actions of the chord: `"cycle_modes"`, `"mode:<id>"`,
  `"toggle:<state>"` (the LED shows the state or mode). `"toggle:<mode>"` picks the mode, and the next press gives
  it back to the rules (`auto`); its LED is on while it is the mode. A fader and an encoder only take
  `"homeassistant"`.
- A slot has one table of controls or a list of them: the first whose `when` holds acts, the others don't (a
  migrated layout per entry). The entries of a slot may share an `id`; another slot can't have it.
- A claimed control wins over what the slot shows and owns its LED or ring; the presenter bound there is told which
  are taken. With the fader taken, the encoder of what the slot shows sets the volume, as with today's
  `fader = "homeassistant"`; with only the encoder taken, the fader stays the volume. Under a claimed Select the LED
  is the launch's. A candidate of the slot can't set the LED (`rec`, `solo`) of a claimed button, also while the
  claim's `when` doesn't hold: one owner per LED in the file.
- A channel's own `fader`/`encoder = "homeassistant"` (entities by channel id, moving with the channel) stays; a
  claim of the slot wins over it while it holds.
- `when` (states only, no `present`): while it doesn't hold, the controls go back to what the slot shows. Starting
  Mumble on slot 7 outside a call leaves VoIP's own Select alone in a call. Nothing changes under a finger: a held
  slot keeps its claims until it is let go, and a release goes to whoever got the press.
- Controls don't touch the resolver: they don't hold a slot, people and channels sit there as anywhere. The Solo
  buttons of the chord can't be claimed.
- Their entities are `*.xtouch_slot_<n>_*`, or `*.xtouch_<id>_*` with `id`: registered once per configuration,
  always there, they follow the slot rather than what it shows.

### Pitfalls the design makes possible

- **Launch**: a channel with `launch` can only be launched while a slot shows it. `"voip if call"` hides VoIP
  exactly when you'd press Select to start the voice chat: put the launch into `[controls]` with `when = "not
  call"`. `check-config` warns.
- **Indicators**: a hidden channel's LEDs are not on the device. `mic if call` hides the Mic and its Rec LED, which
  lights while any application records (a meeting in a browser tab, OBS).
- **A voice chat without room**: people in a Mumble call while no `auto` slot is free for them wait; the why line
  says so ("Bob waits").

### Home Assistant

| Entity | What |
|---|---|
| The entities of a channel (`number.xtouch_<id>_fader`, `select.xtouch_<id>_output`, ...) | As today's strips, named by the channel id, registered once per configuration: they stay available (and keep their state) while the channel is not shown or moves to another slot; the buttons of a `homeassistant` channel send events only while it is shown. |
| The entities of the controls of a slot (`number.xtouch_slot_<n>_fader`, `event.xtouch_slot_<n>_buttons`, ..., or `<id>` instead of `slot_<n>`) | Registered once per configuration, always there, whatever the slot shows. |
| `binary_sensor.xtouch_<id>_shown` | Whether the channel is on a slot. |
| `sensor.xtouch_slot_<n>` | What slot n shows: a channel id (also one `auto` hands out), `app:<application>`, `person:<name>`, or `none`. Attributes `label`, `kind` (`channel`, `app`, `person`, `none`), `via` (the candidate: a channel or pool id), `reason`. |
| `binary_sensor.xtouch_state_<id>` | The state. Attributes `since`, `source` (which source turned it on), `override`. |
| `select.xtouch_state_<id>` | The override: `auto`, `on`, `off`. |
| `switch.xtouch_state_<id>_input` | Only for `homeassistant = true`: what Home Assistant feeds into the state. |
| `select.xtouch_mode` | The mode override: `auto` and every mode. Replaces `select.xtouch_layout`. |

### The chord

`[switching] chord = { strips = [1, 8], action = "cycle_modes" }` (default). `action = "toggle:call"` toggles the
override of a state instead (`auto` -> the opposite of its value now -> `auto`). The same actions are those of
buttons in `[controls]`; the Solo buttons of the chord can't be claimed there.

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
meter = true

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
in_pool = false             # notification sounds of Discord don't take an auto slot

[channel.mic]
type = "input"
device = "alsa_input.pci-0000_11_00.4.analog-stereo"
label = "Mic"
color = "red"
encoder = "balance"

[pool.auto]
color = "white"

[pool.people]               # they take auto slots from the right (next to VoIP), applications from the left
color = "yellow"

[state.gaming]
mode = true
label = "Gaming"
processes = ["@steam-games"]
apps = ["@games"]

[state.call]
voice_chat = true
recording = ["discord", "vesktop"]
delay_on = 0               # voice_chat and recording have no blips to swallow
delay_off = 5               # VoIP and Mic stay through a reconnect, not much longer

[slots]
1 = "out"                       # always the speaker/phones/buds
2 = "browser"
3 = ["game if gaming", "auto"]  # the game next to the browser
4 = [{ show = "auto", rec = "recording" }]
7 = ["voip if call", "auto"]
8 = ["mic if call", "auto"]
```

What it shows, as `xtouch-daemon simulate docs/design/channels-states-slots.toml --table` prints it (the example is
[that file](channels-states-slots.toml); a test keeps this table in line with it): one row per combination of states
and presence the stacks ask about that changes something.

```
when             1    2        3     4-6   7     8
default          out  browser  auto  auto  auto  auto
call             out  browser  auto  auto  voip  mic
gaming           out  browser  game  auto  auto  auto
gaming and call  out  browser  game  auto  voip  mic
```

- People share the auto slots: they
  sit as a block from the right, next to VoIP, in their order (`order`, then the order they were first seen in);
  applications fill the auto slots from the left. A person takes the slot of an application only if no auto slot is
  free, and the application moves to a free one or waits.
- With Mumble, joining a channel turns `call` on at once (`delay_on = 0`): VoIP, Mic and the person show up
  together. Leaving shows at once on the person's strip; VoIP and Mic stay 5 s, through a reconnect.
- A candidate can set options of its strip: slot 4 sets `rec` (here to its default, the REC LED shows recording).

## The GUI

A left rail with four pages; the header and the footer (problems, undo, save) stay as they are.

```
┌──────┬────────────────────────────────────────────────────────────────────────────────┐
│ ▣    │ call ● 21:04 ▾   gaming ○ ▾   wireless ● ▾   night ▨ on ⟲      [▷ Simulate]    │
│Device├────────────────────────────────────────────────────────────────────────────────┤
│ ≡    │  [ the live device as today: LCDs, meters, faders, buttons, 8 strips ]         │
│Chan- │ ┌─1──────────┐┌─2────────────┐┌─3──────┐ ··· ┌─7──────────────┐┌─8──────────┐ │
│nels  │ │  Game      ││▶ Browser     ││▶ auto  │     │▶ VoIP          ││▶ Mic       │ │
│ ◐    │ │  gaming    ││  always      ││ always │     │  call          ││  call      │ │
│States│ │▶ Out       ││ + add        │└────────┘     │  auto          ││  auto      │ │
│ ⚙    │ │  always    │└──────────────┘               │  always        ││  always    │ │
│Sett. │ │ + add      │                               │ + add          ││ + add      │ │
│      │ └────────────┘                               └────────────────┘└────────────┘ │
│      │ Slot 1 · Out: game doesn't hold (gaming is off)             [Slots | Grid]     │
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
    channel or pool in one panel; it says where else that channel is used. Below the card, the slot's
    **controls**: per fader, encoder and button what it does whatever the slot shows, with their `when`.
  - **Grid** shows the distinct outcomes, as in the example above. Clicking a row simulates it, clicking a cell
    selects that card.
- **Channels**: channels and pools, `people` with its look, `order`, and the learned order live, to drag into
  `order`) in a list with type icon, label, tags and where they are used. The inspector is
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
# delay_off = 5
#
# [state.gaming]             # a mode: while a game from Steam runs
# mode = true
# processes = ["@steam-games"]
```

## The daemon

Slots replace strips and layouts in the daemon (no translation into today's strips): what lives as long as the
daemon, the configuration or a member, and a binder that changes only the slots whose result changed.

| Part | Lives as long as | What |
|---|---|---|
| `Desk` (`runtime/desk.py`) | the daemon | The 8 strips of the device: the touch, buttons and touchless faders (`held_slots()`), the events to the presenter bound to each slot, the meters of the bound presenters, banners and flashes. Replaces `Mixer` and `Flow`. |
| `SlotEngine` (`runtime/slots.py`) | the daemon | The `StateEngine`, presence, the members of the pools, the resolver with dwell, pins and the order of the people; keeps overrides, the mode pick and the people across restarts; wakes at the deadlines of the delays (no polling). A reload carries the run state over by state, channel and member id. Replaces `SlotRunner` and `LayoutSwitcher`. |
| `ChannelSet` (`runtime/channels.py`) | the configuration (diffed by id on reload) | One controller per channel, with its own `VirtualStrip`, and its entities, registered once. |
| `Members` (`runtime/members.py`) | a member | A controller per application of `auto` (today's `AutoStrip` without `AutoSlot`) and per person (today's `voip` strip with a participant id, without `VoipSeats`): made when it becomes a member, closed when its `hold` or `absent_after` ends; it moves between slots unchanged. |
| `Places` (`runtime/places.py`) | the configuration | The options of `auto` candidates: their look, and what acts on the application without a channel they show (the `pick`, `media`, `volume`, `balance` encoder, the volume range). |
| `Controls` (`runtime/controls.py`) | the configuration | The `[controls]` of each slot with their entities: bound to the `Desk`'s slot, not to what it shows; they take the claimed controls from the presenter while `when` holds. |
| `Binder` (`runtime/binder.py`) | the daemon | Compares a result with the one before and binds only the slots that changed (`VirtualStrip.bind`); unbinds what is no longer shown; the flashes and their reason. A controller gets its look (label, color, `lit_when_idle`, `rec`, `solo`, `meter`, `meter_point`) when it is bound, its identity is its channel or member. |
| Home Assistant (`runtime/homeassistant.py`) | the configuration | The entities of states, overrides, the mode and the slots. |
| Live view | | A snapshot of the slots (per slot the candidate, channel, pool, member and why), the states (value, since, source, override), the mode and who waits; requests `SetMode` and `SetOverride`. |

- Goes away: `Mixer`, `placement.py`, `layouts.py`, `AutoAssigner`/`AutoSlot`, `VoipSeats`, `Shape`/`DARK`/`showing`,
  `config/strips` (the `[[strip]]` types), the layouts, `inheritance`, and handing the applications of `apps`
  channels to `behavior.ignore`.
- The resolver alone decides which member shows where; the encoder's pick and pins are requests to the `SlotEngine`.
- Times come from the loop's clock (`loop.time()`).
- `check-config` prints channels, pools, people, states with their sources, per slot its stack, the outcome table,
  and the warnings above. `list-apps` says per application which channel, pool or slot has it.

### The order of the work

Each step keeps the daemon working and the tests green:

1. The format: `[people]`, no `people` candidate (both revised in [people-slots.md](people-slots.md)), people skip
   pins, `person` channels in the block, the presence of `auto`, typed members, `[controls]` (read and checked; they
   run from step 5c on), `talking_color` only for people.
2. `Desk` out of `Mixer`, for both formats: touch and held buttons survive a new mixer. See [Step 2](#step-2-the-desk).
3. Controllers get their look, identity and entity ids from outside (the old format from its strips).
4. `SlotEngine` with pins, overrides and persistence, carried over a reload; the prototype takes the applications of
   `auto` from the result. Pins hold a typed member (application or channel, like `Person`), people go by the
   participant's id.
5. The slots natively: `ChannelSet`, `Members`, `Places`, `Controls`, `Binder` on the `Desk`; `Shape` and the
   rebuilding go; entities per channel and per slot's controls.
6. Home Assistant: states, overrides, the mode (replaces the layout select), the slots. The chord gets its new form,
   and its check against `[controls]` moves into `Scene.of()` (now in `config/slots.py`).
7. The live view: the snapshot and requests above; the GUI shows them read-only.
8. `check-config`, `init-config`, the docs. `migrate-config` was not built: the old format is a clean break, an old
   file fails `check-config`.
9. The old format and its runtime go.
10. The GUI edits the new format.

### Step 2: the Desk

- `Presenter`: what the `Desk` calls of a controller (today's `StripController`): `strip`, the `on_*` handlers,
  `meter_targets`, `is_playing`, `target_gain`, `held_meter`, `close`, and `taken_controls` (step 5).
- The `Desk` API: `bind(slot, presenter | None, meter_point)`, `held_slots()` (slots from 1), `dispatch(event)`. A
  presenter bound to a slot a finger is on gets `on_touch(True)` at once, so it knows (in the old format a layout
  switch rebinds under a finger; in the new one a held slot doesn't change).
- `dispatch` routes by slot and control (fader, encoder, each button) to an owner: the bound presenter, or a claim
  (a hook that stays empty until step 5 brings `[controls]`). It is sticky: a release (button up, encoder push up)
  goes to whoever got the press, even if `bind()` changed in between. A touched fader goes over instead: on `bind()`
  the presenter that had it gets `on_touch(False)`, the new one `on_touch(True)`, its moves and its release, so each
  sees a touch and its release.
- Until step 9 the old format binds the controllers of its mixer through the `Flow` (`strip_at`).
- The `Desk` owns the meters from step 2 on: it runs the meter loop for the presenters bound now.
- The `Desk` also keeps the chord's held Solo buttons and the flashes and banners of the slots.
- The GUI's live preview uses the same `Desk`: touch and held buttons carry over its start and end.
- Tests: `tests/runtime/test_desk.py` with what moves from `test_mixer.py`, and "a finger on fader 2 during a change
  of slot 7 keeps slot 2 as it is, and the new presenter of slot 2 knows about the finger".

### Step 9: the old format goes

Decided 2026-11-17: step 9 before step 10; the GUI may not edit configurations in between.

- **9a, reading**: the old `Config` (strips, layouts and their checks), `LayoutConfig`, `InheritStripConfig`,
  `Inheritance` and the old-only options (`behavior.auto_hold`, `ignore`, `collapse_hold`, `switching.hold`) move
  to `config/legacy/` (the GUI read it until step 10; it is gone now). `parse_config` refuses a file
  with `[[strip]]` or `[[layout]]`; a file without `[slots]` is one of channels,
  states and slots with all slots `auto`, so `Config.slots` is always there. The defaults without a file are
  `config.example.toml`.
- **9b, runtime**: the daemon runs only slots: `Mixer`, `runtime/layouts.py` (`LayoutSwitcher`, `layout_file`),
  `placement.py`, `AutoAssigner`/`AutoSlot`, `VoipSeats`, `collapse` in the strips, `select.<ns>_layout`, and in the
  live view `layout`, `layouts`, `placement` and `SwitchLayout` go; `xtouch-daemon layout` fails with a pointer to
  `mode`. The binder reads `hold` and the excluded applications from the scene, not from `[behavior]`.
- **9c, commands**: `check-config` describes channels, states and slots (the table, and per channel what it is),
  `list-apps` says which channel, pool or slot takes each application, `test` and `run` as before.
- **9d, docs**: the pages of strips, layouts and collapsing go into Channels, states and slots; Getting started, Home
  Assistant, Commands, Architecture and the example follow.

### Step 10: the GUI edits the new format

Decided 2026-11-17: the whole of [The GUI](#the-gui), in these commits:

- **10a, the document**: `gui/domain/slots_document.py`, the file as plain data with option paths
  (`("channel", "mic", "label")`, `("slots", "3")`, `("state", "call", "delay_off")`), written back into the TOML
  text with its comments and the form of each stack. An old file fails to open with the errors of `check-config`. `validate()` runs `parse_config()` and gives each problem its path. Undo as today.
- **10b, the rail, Settings and Channels**: a left rail (Device, Channels, States, Settings); Settings are today's
  section pages; Channels lists channels and the pools (`apps`, `people`, `auto` and those of channels) with type, label, tags and where they are
  used, the inspector is today's strip form, with Add, Duplicate and Remove.
- **10c, States**: modes first, then the other states: sources or `when`, delays, `persist`, live value since when
  and from which source, the override, and which stacks use it.
- **10d, Device**: the live device with the state bar (live, override menus) above slot cards: each stack as rows
  with their conditions as chips, ▶ on the one shown, add, remove, Ctrl+Up/Down and drag and drop; the inspector
  edits the candidate (show, condition as chips or text, place options) and its channel, and says where else the
  channel is used; below it the controls of the slot.
- **10e, why**: the why line from the resolver's trace for a slot or a channel, and `xtouch-daemon why <slot or
  channel>`.
- **10f, Simulate and Grid**: Simulate (a frame around the device, a bar of what-if inputs, the device shows what
  the resolver would, nothing is sent, Esc ends it) and the Grid of distinct outcomes (a row simulates it, a cell
  selects its card).
- **10g, the old GUI goes**: strips and layouts in the GUI, `config/legacy`, the old example
  and `init-config --strips`, `layout`, `layouts`, `placement` and `SwitchLayout` of the live view; the GUI page and
  its screenshot follow.

## Migration

Not built (decided 2026-11-17: a clean break). An old file fails `check-config`; this is how to write it anew:

| Old | New |
|---|---|
| A strip | A channel and a candidate in the slot of its position. Its id: its `id`; for a strip with Home Assistant entities `strip_<position>` (so `select.xtouch_strip_1_output` keeps working), with a suggestion to rename it; else its label in lower case, else `<type>_<n>`. |
| `homeassistant` strips that share entities across layouts | One channel. |
| An `auto` strip | `auto`; its options that differ from those of the other `auto` strips become options of the place. Candidates the same as the slot's fallback are dropped. |
| A `voip` strip | Without `person`: a `people` candidate, its look goes to `[pool.people]`; people fill slots from the right in their order, so their strips move; `label` and paging go. With `person`: a `person` channel. A `launch` goes to `[controls]` of its slot, `select = { launch = ... }` (decision 6). |
| `fader`/`encoder = "homeassistant"` and `launch` of an `auto` strip | `[controls]` of its slot, with `id = "strip_<n>"` so the entities keep their ids. |
| An `empty` strip | `"-"`. |
| A `[[layout]]` | A `[state.<name>] mode = true` with its rules, label and priority; each of its strips a candidate `if <name>` above the default one of that slot. |
| `meter_point` of a layout | `meter_point` on the places of its candidates. |
| An `inherit` strip | A candidate of the channel it refers to. The report names every one it resolved, so surprises (like the one in the motivation) show. |
| `collapse` on a strip | The strip stays in its slot as `"<id> if present"` above `auto`: nothing shifts any more. The report lists them and points to pools of channels for those who want filling by order. |
| `behavior.auto_hold`, `behavior.ignore` | `[pool.apps] hold`, `exclude`. |
| `behavior.collapse_hold` | `behavior.absent_after`. |
| `switching.hold` | `delay_off` of each mode. |
| `switching.chord = [1, 8]` | `chord = { strips = [1, 8], action = "cycle_modes" }`. |
| The remembered layout (`layout_file`) | The kept override of the mode. |
| Strips with the same `strip_<n>` entities in several layouts that control different things | Separate channels; the report names the entities that are renamed. |
| `select.xtouch_layout`, `xtouch-daemon layout` | `select.xtouch_mode`, `xtouch-daemon mode`; the old command fails with a pointer, the report names the entity for automations. |

No compatibility reading of the old format.

## Tests the design needs

The resolver and the state engine are pure, so each rule gets unit tests, among them every scenario the reviews
traced:

- the example's table, row by row, and joining Mumble while gaming (VoIP, Mic and the person at once);
- a channel several stacks want at the same and at different ranks; an exhausted stack ending in `auto`; `"-"`;
- a held slot keeping a channel another slot now ranks higher; a touchless fader moved by the user and by the motor;
- pool members keeping their slots and waiting (6 applications, then a call); `pick` and pins; people in their
  order from the right, moving applications only when needed;
  a pool of channels filling by order; a hidden channel taking an `auto` slot as a whole, and `in_pool = false`;
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
it), the touch sensors (their result is `held`), reload carrying the result over, cycling
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

**On the device**: the daemon runs a file in this format (`xtouch-daemon run -c slots.toml`). The resolver runs
every 0.2 s (that is the batching) on what the sound server, the processes and the voice chat of the daemon show.
Each channel has its controller for as long as the configuration, each application of `auto` and each person
without a channel one while they are members (`SlotMixer` in `runtime/binder.py`, step 5b); after each step only the
slots whose result changed get another controller, so the others keep their texts, fader and LEDs; a slot that
shows another candidate flashes its label and why (the `when` of the new candidate, or `not <when>` of the old one)
for `switching.banner` seconds, unless the mode changed (its banner says it). `[controls]` run
(`runtime/controls.py`, step 5c): the first entry of a slot whose `when` holds claims its controls on the `Desk`,
shows their fader, ring and LEDs, and launches, picks modes, toggles states or puts them into Home Assistant. Apps
channels never go into `auto` one application at a time, only as a whole. The mode takes the place of the layout:
`xtouch-daemon layout gaming`, the GUI and the chord pick a mode, `layout auto` gives it back to the rules; the
banner names a new mode. With `[mqtt]`, Home Assistant has the entities of [Home Assistant](#home-assistant)
(`runtime/homeassistant.py`, step 6). Not yet: the GUI (it can't edit the format).

Next: see [Decisions after the live test](#decisions-after-the-live-test).

## Decisions after the live test

The prototype ran on the author's device (the example above). Decided then:

1. **People only share `auto`** (revised 2026-11-17 in [people-slots.md](people-slots.md): `people`, `apps` and
   `auto` are built-in pools). `people` is no candidate of a slot any more, and `share` goes: people always take
   `auto` slots from the right, in their order. One way to place people; no paging. Fixed people are `person`
   channels.
2. **Slots replace strips and layouts in the daemon.** Not a translation into today's strips: channel controllers
   that live as long as the configuration, bound to slots by the resolver ([The daemon](#the-daemon)).
3. **The conditions stay as they are** (`"x if y"` strings with the grammar above): they read well and worked on
   the device.
4. **One format.** The old one goes: no reading of it, and no `migrate-config` either ([Migration](#migration)).
   The GUI, the docs and `init-config` move to the new format.
5. **`person` channels without a slot join the people** as themselves (`in_pool` to opt out), like `apps` channels
   join `auto`.
6. **Starting the voice chat** is a control of the slot VoIP shows on: `7 = { select = { launch = [...] }, when =
   "not call" }` in `[controls]`; the VoIP channel stays hidden outside a call, the strips of people have no launch.
7. **`[people]`**, not `[pool.people]`: people are no pool any more (revised 2026-11-17: `[pool.people]`).
8. **`[controls]`**: actions that belong to a slot, whatever it shows ([Controls](#controls)). Options of places
   only look, or act on applications without a channel.

Found on the device and changed in the prototype: `call` on at once and off after 5 s (a delay showed VoIP and Mic
after the people, a long one hid leaving); people in a learned order instead of fixed home slots (no empty slots);
people from the right, applications from the left (they don't push each other around); `voice_chat` also alone (the
mic before anyone comes); the meters of people on the dB scale like every other meter.

## Review log

### Sixth review (the integration of the fifth)

| Finding | Decision |
|---|---|
| A pinned member a held slot shows went to its pin's slot too: one stream on two strips. | A pin waits while a held slot shows its member. |
| Claims could change under a finger; a release could go to another owner than the press. | Held slots keep their claims; `dispatch` is sticky and routes by control. |
| Minor: untyped pins and members by display name; an `id` on controls without Home Assistant; an empty launch; `launch_when_running` in `[people]`; LEDs of claimed buttons with a `when`; the chord check outside the model; two homes for Home Assistant faders; LEDs under claims. | Step 4; errors; refused; one owner per LED; step 6; both stay, the slot's claim wins; stated. |
| `bind()` lacked the meter point the `Desk` needs for its meters. | `bind(slot, presenter, meter_point)`. |
| **Owner**: one table of controls per slot can't change with the mode (layouts with different controls on a strip). | A list per slot, the first whose `when` holds. |
| **Owner**: `toggle:<mode>` had no meaning (modes have no override of their own). | Picks the mode, the next press back to `auto`. |

### Fifth review (the integration of the fourth, and actions of places)

| Finding | Decision |
|---|---|
| Actions (a Home Assistant knob, a launch) only worked through what the slot showed: a channel or a person there silently disabled them. | `[controls]` per slot (decision 8). |
| **Blocker**: participant names and channel ids were one namespace of members: someone called `browser` became the Browser channel and broke the strips. | Typed members (application, channel, person). |
| Options that kept people off a place disagreed between code and design; place ids couldn't be reused; decision 6 hung on people skipping places. | Gone with `[controls]`: only pins keep people out. |
| Minor: `launch` in `[people]`; a `[voip]` provider in every configuration; `auto` present for people who never sit in it; a dropped pin kept people out; the table doesn't explore people; participant ids. | Refused; said in the design (people share `auto` everywhere, the bridge socket costs nothing without a voice chat); fixed; fixed; Simulate gets a count of people (step 7); step 4. |
| Doc: the `Places` row against the people rule, a fifth review that didn't exist, where `[people]` is edited, "then the people" as a pool. | Fixed. |
| Step 2 not concrete. | [Step 2](#step-2-the-desk). |

### Fourth review (architecture, after the live test)

| Finding | Decision |
|---|---|
| **Blocker**: entities were named by strip (`strip_<n>`) and went away with a channel's slot; place options overrode a channel's controls and `id`. | Entities per channel and place id, registered once per configuration; place ids in the namespace; place options only for applications without a channel. |
| **Blocker**: the mixer handed out the applications of `auto` itself, in its own order, next to the resolver; pins never reached the resolver. | The resolver alone; pick and pins are requests to the `SlotEngine`. |
| Touch and held buttons died with each new mixer. | The `Desk` lives as long as the daemon. |
| People on places with controls, people and pins. | People skip pinned slots and places with control options; pick only lists applications. |
| The presence of `auto` didn't count people. | It does. |
| `person` channels without a slot vanished. | They join the people (decision 5). |
| Leftovers of `share` and the `people` candidate. | Gone; `[people]`. |
| A reload lost the run state. | The `SlotEngine` outlives the configuration. |
| Controllers had their place built in; the live view counted strips by layout. | Look and identity when bound; a snapshot of slots and states. |
| The voice chat's `launch` had no home. | A launch on the place VoIP leaves (decision 6). |
| Minor: clocks, people by name, `sensor.xtouch_slot_<n>`, migration rows, polling, entity churn of the prototype. | `loop.time()`, ids for members, the sensor's format, the rows, deadlines; the native runtime ends the churn. |

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
| **Blocker**: the example's table showed a scene that barely exists (people present means `call` with Mumble) and slot 8 changed twice. | The example asked `people if gaming and present` and dropped Browser from slot 8 (replaced after the live test: people share `auto`). |
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
