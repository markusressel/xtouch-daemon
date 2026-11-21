# In the daemon

Part of [Design: channels, states and slots](index.md). The modules are in [Architecture](../../architecture/index.md).

## The runtime

Slots replace the strips and layouts of the old format in the daemon natively (no translation into strips): parts
that live as long as the daemon, the configuration or a member, and a binder that changes only the slots whose result
changed.

| Part | Lives as long as | What |
|---|---|---|
| `Desk` (`daemon/desk.py`) | the daemon | The 8 strips of the device: touches, held buttons and touchless faders (`held_slots()`), the events to the presenter bound to each slot or to a claim, the meters of what is bound, banners and flashes. |
| `SlotEngine` (`daemon/slots.py`) | the daemon | The `StateEngine`, presence, the members of the pools, the resolver with dwell, pins and the order of the people; keeps overrides, the mode picked and the people across restarts; wakes at the deadlines of the delays (no polling). A reload carries its state over by state, channel and member id. |
| `SlotMixer` (`daemon/binder.py`) | the configuration | A controller with its own `VirtualStrip` per channel, per application of `auto` and per person without a channel while they are members (made when it becomes one, closed when its `hold` or `absent_after` ends; it moves between slots unchanged). Binds only the slots whose result changed; a controller gets its look and the options of its place when it is bound, its identity is its channel or member. |
| `Controls` (`daemon/controls.py`) | the configuration | The `[controls]` of each slot with their entities, bound to the `Desk`'s slot, not to what it shows. |
| `SlotEntities` (`daemon/homeassistant.py`) | the configuration | The entities of the states, overrides, the mode and the slots. |

- Times come from the loop's clock (`loop.time()`).
- **The `Desk`** routes by slot and control (fader, encoder, each button) to an owner: the bound presenter or a claim.
  It is sticky: a release goes to whoever got the press, even if a `bind()` came in between. A touched fader goes over
  instead: on `bind()` the presenter that had it gets `on_touch(False)`, the new one `on_touch(True)`, its moves and
  its release, so each sees a touch and its release. A live preview uses the same `Desk`, so touches and held buttons
  carry over its start and end.

## Home Assistant

| Entity | What |
|---|---|
| The entities of a channel (`number.xtouch_<id>_fader`, `select.xtouch_<id>_output`, ...) | Named by the channel id, registered once per configuration: they stay available (and keep their state) while the channel is not shown or moves; the buttons of a `homeassistant` channel send events only while it is shown. |
| The entities of the controls of a slot (`number.xtouch_slot_<n>_fader`, `event.xtouch_slot_<n>_buttons`, ..., or `<id>` instead of `slot_<n>`) | Registered once per configuration, whatever the slot shows. |
| `binary_sensor.xtouch_<id>_shown` | Whether the channel is on a slot. |
| `sensor.xtouch_slot_<n>` | What slot n shows: a channel id, `app:<application>`, `person:<name>`, or `none`. Attributes `label`, `kind` (`channel`, `app`, `person`, `none`), `via` (the candidate), `reason`. |
| `binary_sensor.xtouch_state_<id>` | The state. Attributes `since`, `source` (which source turned it on), `override`. |
| `select.xtouch_state_<id>` | The override: `auto`, `on`, `off`. |
| `switch.xtouch_state_<id>_input` | Only with `homeassistant = true`: what Home Assistant feeds into the state. |
| `select.xtouch_mode` | The mode override: `auto` and every mode. |

## Commands

- `check-config` prints the channels, the outcome table and its notes (see [Slots](slots.md#pitfalls)).
- `list-apps` says per application which channel, pool or slot has it.
- `why <slot or channel>` tells what a slot shows and why not the candidates above it, or where a channel is and why
  not elsewhere (`browser: on slot 2; not slot 8 (on slot 2 (tie, to the left))`); `why people` who sits where and who waits.
- `simulate` and `observe`: the slots of a file in any situation, and a recording of the real system to replay
  (`simulate --replay`).

## The GUI

- **Slots**: each slot is a card with its stack, a row per candidate with its condition as text chips (`call or
  gaming`, `always`) and a tiny LCD in the color of its strip, ▶ on the one shown. Drag and drop or Ctrl+Up/Down
  reorder. The inspector edits the candidate (condition, the options for this place), says where else its channel is
  used and what a pool hands out and from where; below it the slot's controls. The why line is the resolver's trace.
- **Simulate**: what-if inputs (every state, the presence the stacks ask about, how many people are in the call and
  applications play); the drawing shows what the resolver would, in the GUI or on the device where "Preview" says,
  see [Previews](../previews.md). Esc ends it.
- **The state bar** is live: each state with its value and since when; its menu sets the override, and an overridden
  state is hatched, with ⟲ back to `auto`.
- **Channels**: channels and pools (the built-in ones below, each with the look of its strips), with type, label, tags
  and where they are used; Add, Duplicate, Remove.
- **States**: modes first, then the other states: sources or `when`, delays, `persist`, the live value since when and
  from which source, the override, and which stacks use it.
- Problems link to a slot, candidate, channel, pool or state. The GUI keeps the form a stack has in the file (string,
  compact list or tables) and its comments.
