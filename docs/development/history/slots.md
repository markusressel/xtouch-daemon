# History: channels, states and slots

How [the design of channels, states and slots](../design/slots/index.md) came to be, from the old format of strips and
[layouts](layouts.md) to 0.1.0. The design itself has only what holds now.

## How it was built

Three reviews of the prose found three rounds of holes, each in the parts that only existed as prose, so the resolver
and the state engine became code first (`xtouch_daemon.slots`, pure, driven by `xtouch-daemon simulate`), then a
prototype on the device, then the daemon natively. Each step kept the daemon working and the tests green:

1. The format, read and checked (`[controls]` ran from step 5 on).
2. The `Desk` out of the old `Mixer`, for both formats: touches and held buttons survive a new mixer.
3. Controllers get their look, identity and entity ids from outside.
4. The `SlotEngine` with pins, overrides and persistence, carried over a reload; typed members.
5. The slots natively: a controller per channel and member, `[controls]`, the binder on the `Desk`; entities per
   channel and per slot's controls.
6. Home Assistant: states, overrides, the mode (replacing the layout select), the slots; the chord's new form.
7. The live view: the snapshot of slots and states, the requests `SetMode` and `SetOverride`.
8. `check-config`, `init-config`, the docs.
9. The old format and its runtime went (decided 2026-11-17, before step 10, so the GUI could not edit configurations
   in between): `Mixer`, `placement.py`, `layouts.py`, `AutoAssigner`, `VoipSeats`, `collapse`, `inherit`,
   `select.<ns>_layout`, the layout parts of the live view. `parse_config` refuses `[[strip]]` and `[[layout]]`;
   `xtouch-daemon layout` fails with a pointer to `mode`.
10. The GUI edits the new format: the document with option paths, the rail, Channels, States, the slot cards, why,
    Simulate (and a grid of the distinct outcomes, removed later).

The people were decided again in a third round ([Where the people sit](../design/slots/people.md)), which replaced
`[people]` with `[pool.people]`, `in_auto` with `in_pool`, and made `apps`, `people` and `auto` built-in pools.

## What building it showed

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


## Decisions after the live test

The prototype ran on the author's device (the [example](../design/slots/index.md#an-example)). Decided then:

1. **People only share `auto`** (revised 2026-11-17 in [people-slots.md](../design/slots/people.md): `people`, `apps` and
   `auto` are built-in pools). `people` is no candidate of a slot any more, and `share` goes: people always take
   `auto` slots from the right, in their order. One way to place people; no paging. Fixed people are `person`
   channels.
2. **Slots replace strips and layouts in the daemon.** Not a translation into today's strips: channel controllers
   that live as long as the configuration, bound to slots by the resolver ([The daemon](../design/slots/daemon.md)).
3. **The conditions stay as they are** (`"x if y"` strings with the grammar above): they read well and worked on
   the device.
4. **One format.** The old one goes: no reading of it, and no `migrate-config` either ([Migration](#migration)).
   The GUI, the docs and `init-config` move to the new format.
5. **`person` channels without a slot join the people** as themselves (`in_pool` to opt out), like `apps` channels
   join `auto`.
6. **Starting the voice chat** is a control of the slot VoIP shows on: `7 = { select = { launch = [...] }, when =
   "not call" }` in `[controls]`; the VoIP channel stays hidden outside a call, the strips of people have no launch.
7. **`[people]`**, not `[pool.people]`: people are no pool any more (revised 2026-11-17: `[pool.people]`).
8. **`[controls]`**: actions that belong to a slot, whatever it shows ([Controls](../design/slots/slots.md#controls)). Options of places
   only look, or act on applications without a channel.

Found on the device and changed in the prototype: `call` on at once and off after 5 s (a delay showed VoIP and Mic
after the people, a long one hid leaving); people in a learned order instead of fixed home slots (no empty slots);
people from the right, applications from the left (they don't push each other around); `voice_chat` also alone (the
mic before anyone comes); the meters of people on the dB scale like every other meter.

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
| Step 2 not concrete. | [Step 2](../design/slots/daemon.md#the-runtime). |

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
| Newcomer configuration and `init-config`. | [A new configuration](../design/slots/index.md#a-new-configuration). |
