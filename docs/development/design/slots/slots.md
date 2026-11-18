# Slots

Part of [Design: channels, states and slots](index.md).

The device has 8 slots, one per strip, numbered 1 to 8 from the left. Each has a stack of candidates, top first.

```toml
[slots]
1 = "out"                   # a single candidate: the same as ["out"]
2 = "browser"
3 = ["game if gaming", "auto"]
4 = [{ show = "auto", encoder = "pick" }]
7 = ["voip if call", "auto"]
8 = ["mic if call", "auto"]
```

- A candidate is `"<channel or pool>"`, optionally with `" if <expression>"`, or `"-"`: deliberately nothing (the
  slot is dark).
- A slot without an entry is `"auto"`. A stack whose candidates all don't hold, or lose, ends in an implicit `"auto"`;
  `"-"` at the end makes it dark instead.
- **Two words** keep the rules apart: a candidate **holds** while its condition is true; a slot **shows** the candidate
  it gets in the end. A candidate without a condition always holds: an absent channel is shown dark and keeps its
  place, an empty pool hands down or is dark. `"spotify if present"` holds only while there is something.
- **Options for this place**, in the table form `{ show = "...", when = "...", ... }`:
  - on any candidate, its look here: `label`, `color`, `lit_when_idle`, `rec`, `solo`, `meter`, `meter_point`;
  - on `apps` and `auto` also what acts on an application without a channel: `encoder` (`pick`, `media`, `volume`,
    `balance`), `min_volume`, `max_volume`; on `people` only `color`, `meter` and `meter_point`.
  - They apply to the members without a channel. A channel shown as a member looks and works as the channel; the
    place only fills in what it leaves open. What a control does whatever the slot shows is in
    [`[controls]`](#controls).

## The resolver

`slots.resolver.resolve()` decides what each slot shows from the inputs (states, presence, pool members, pins, held
slots) and, for the members of `apps`, the previous result. Its trace is what `why` and the GUI tell.

1. **Fixed slots.** A slot that is held (a finger, a button) or within its dwell time keeps what it shows; its channel
   or member is reserved, and the other slots are resolved around it.
2. **Channels by rank.** Every other slot proposes its first candidate that holds. A channel that several slots
   propose goes to the one where it is highest in the stack (its rank), ties to the leftmost slot; the others go on to
   their next candidate that holds. Repeat until nothing changes. A pool takes its slot in this step (pools are not
   contested). It ends: a slot only goes down its stack.
3. **Pools.** The members are handed out:
   - **Chain.** The pool a slot shows after step 2, and the candidates below it that hold while they are pools, up to
     and with a `-`, form the slot's chain; a channel ends it. `["people if call", "- if call", "auto"]` while `call`
     is on: `people`, `-`.
   - **Hand-down.** A pool with no member for a slot leaves it to the next pool of the chain. A slot no pool fills
     shows the last pool of its chain, dark, or `-`.
   - **Pools of channels first**, in the order of the file, each from its side. One below `apps`, `people` or `auto`
     in a chain is an error: those take the channels that no pool of channels gives a slot.
   - **Contest.** Then the people over the slots whose chain has `people` or `auto`, in their order; the applications
     over those with `apps` or `auto`: pins first, then each on the slot it had, then in their order. A slot both fill
     goes to the one higher in its stack (inside `auto`, the people); the other gives it up and is handed out again,
     until nothing changes. It ends: each only loses slots. Members left over **wait**.
   - **Fill order.** Each from its side; the people first take the slots where they are the first candidate, then
     the others (see [Not a block](people.md#not-a-block)).
   - A pin reserves its slot if the chain there has `apps` or `auto`; a pin waits while a held slot shows its member,
     and a pin of a channel that has a slot of its own is dropped (one channel, one slot).

Conditions never look at the result, so the steps run once each, in this order: the same inputs give the same result.

## Stability

- **Batching**: changes are resolved together 0.1 s after the first one (`runtime/slots.BATCH`): a game starts
  several streams and a process at once, and the faders move once.
- **Dwell**: a slot keeps what it shows for at least 1 s before it changes again (`slots/simulation.DWELL`).
- **Nothing changes under a finger**: a held slot is fixed (step 1) until let go, with its claims. A fader in
  `touchless_faders` counts as touched while the user moves it and half a second after; the motor moving it doesn't
  count. The buttons of the chord don't hold slots.
- **Startup**: the daemon waits for the first state of the sound server and the first process scan, evaluates the
  states without `delay_on` (the baseline), restores the overrides, and only then runs the startup sequence: the first
  picture is the right one.
- **Reload**: the previous result carries over by channel id and member.

## Telling what changed

A slot that shows something else flashes the new label on the top line and why on the bottom line (the `when` of the
new candidate, or `not <when>` of the old one) for `switching.banner` seconds. A new mode shows its label across all
LCDs instead. The motor fader moves to the new volume, as with banking in a DAW. The log has one line per change with
the reasons.

## Controls

What a fader, encoder or button of a slot does whatever the slot shows: actions of the place, not of a channel.

```toml
[controls]
4 = { encoder = "homeassistant" }                        # number.xtouch_slot_4_encoder and push events
7 = { select = { launch = ["mumble", "mumble://..."] }, when = "not call" }
1 = { solo = "toggle:night", rec = "homeassistant" }
2 = { fader = "homeassistant", id = "desk_fader" }       # number.xtouch_desk_fader_fader
3 = [                                                    # the first whose when holds
    { encoder = "homeassistant", id = "strip_3", when = "gaming" },
    { select = { launch = ["obs"] } },
]
```

- **What can be claimed**: `fader`, `encoder` (turn and push), `select`, `rec` and `solo`; not Mute, which stays with
  what the slot shows, and not the Solo buttons of the chord.
- **Actions**: `"homeassistant"` (a number for the fader or encoder, events for the buttons, a select for their LED),
  `{ launch = [...], launch_when_running = ... }`, and the actions of the chord: `"cycle_modes"`, `"mode:<id>"`,
  `"toggle:<state>"` (the LED shows the state). `"toggle:<mode>"` picks the mode, and the next press gives it back to
  the rules; its LED is on while it is the mode. A fader and an encoder only take `"homeassistant"`.
- **One table or a list**: the first entry whose `when` (states only, no `present`) holds acts. The entries of a slot
  may share an `id`; another slot can't have it.
- **A claim wins** over what the slot shows and owns its LED or ring; the presenter bound there is told which controls
  are taken. With the fader taken, the encoder of what the slot shows sets the volume; with only the encoder taken, the
  fader stays the volume. A candidate can't set the LED (`rec`, `solo`) of a claimed button, also while the claim's
  `when` doesn't hold: one owner per LED in the file.
- A channel's own `fader`/`encoder = "homeassistant"` (entities by channel id, moving with the channel) stays; a claim
  of the slot wins while it holds.
- **Controls don't touch the resolver**: they hold no slot, and people and channels sit there as anywhere. A release
  goes to whoever got the press.
- **Entities**: `*.xtouch_slot_<n>_*`, or `*.xtouch_<id>_*` with `id`: registered once per configuration, always there,
  following the slot rather than what it shows.

## Pitfalls

- **Launch behind a condition.** A channel's `launch` works only while a slot shows it. `"voip if call"` hides VoIP
  exactly when you'd press Select to start the voice chat: put the launch into `[controls]` with `when = "not call"`.
- **Hidden indicators.** A hidden channel's LEDs are not on the device: `mic if call` hides the Mic and its Rec LED,
  which lights while any application records (a meeting in a browser tab).
- **A voice chat without room.** People in a call while no slot is free for them wait; the why line says so
  ("Bob waits").
- **Rank surprises.** `1 = ["buds if present", "out"]` and `3 = ["out if video", "auto"]`: in video mode without buds,
  `out` goes to slot 3 (rank 1 there, 2 on slot 1), and slot 1 shows `auto`. Correct, but only the outcome table,
  Simulate or `why` make it visible.

`check-config`'s notes (`slots/outcomes.notes()`) name a channel right below a pool without a condition (it never
shows) and people with no slot to sit on.
