# Pools of your own

Part of [Design: channels, states and slots](index.md). Status: **proposed** (2026-11-19), not built. Today a
`[pool.<id>]` can only list channels ([Pools](channels.md#pools-one-of-several)); the pools of applications, people and
devices are built in. This page adds pools of applications and of people that the user defines.

## Why

The built-in `apps` pool hands out every application that plays and has no slot, in the order they started. That is
one pool for everything. Wishes it can't express:

- "The music players on slot 5, whatever else plays": `apps` would put a browser tab there as well.
- "My friends first, on the left": the pool `people` has one `order`, one side and one look for everybody.
- Two groups of applications on different sides of the device, each in its own color.

A channel can't do it either: an `apps` channel is one strip over all its streams, and one fader moves them together.
What is missing is a pool that selects the applications (or people) that qualify, and still gives each its own strip.

## The format

`[pool.<id>]` gets an optional `kind`. Without it, the section is a pool of channels, as today, so no file changes.

```toml
[pool.music]
kind = "apps"
match = ["@music"]            # presets and parts of names, as in an `apps` channel
exclude = ["spotify-ads"]     # optional: never these, though they match
from = "left"                 # the side it fills its slots from (default)
hold = 5                      # seconds a slot keeps an application after it stopped (default)
color = "green"               # the look of its strips, as in [pool.apps]

[pool.friends]
kind = "people"
people = ["Alice", "Bob"]     # names in the voice chat; this order is their order
from = "right"                # default: left for apps, right for people, as the built-in pools
color = "yellow"
talking_color = "green"

[slots]
5 = ["music", "apps"]         # a music player if one plays, else the next other application
6 = ["friends", "people"]     # Alice and Bob first, then anyone else in the call
```

Two kinds, no mixed pool. A pool of applications and a pool of people share a slot by being two candidates of its
stack (`["friends", "music", "auto"]`), as the built-in ones do.

| Option | `kind = "apps"` | `kind = "people"` |
|---|---|---|
| `match` | Required. Parts of application names or binaries, presets allowed. | Not allowed. |
| `exclude` | Optional, as in `[pool.apps]`. | Not allowed. |
| `people` | Not allowed. | Required. Names as in `person` of a channel (case-insensitive, whole names). |
| `from` | Default `left`. | Default `right`. |
| `hold` | Seconds, default 5. | Not allowed: people stay `absent_after` seconds, like the built-in pool. |
| look (`color`, `meter`, `meter_point`, `rec`, `solo`, `lit_when_idle`) | The look options of `[pool.apps]`. | The look options of `[pool.people]` (`talking_color` too). |
| `encoder`, `min_volume`, `max_volume` | As in `[pool.apps]`. | Not allowed: the strips of people have none. |

Errors use the existing words: a missing `match` is `pool.music: kind apps needs match`; an option of the other kind
names where it belongs (`people: an option of kind people`). A `kind` other than the two lists them.

## What it takes

Every member belongs to one source, and the first source that qualifies takes it. The order is fixed, from the most
specific to the most general:

1. **Channels.** An application of an `apps` channel that has a slot, and a person of a `person` channel, are the
   channel's, as today.
2. **Pools of your own**, in the order of the file: pools of people, then pools of applications. A member that two of
   them could take goes to the one that comes first in the file.
3. **The built-in pools.** `apps` and `auto` take the applications that nothing above took, `people` and `auto` the
   people.

So `music` takes a music player out of `apps` and `auto`, as an `apps` channel with a slot already does. A pool of your
own takes its members **only while a slot names it** (in any stack, shown or not), like a channel with a slot. A pool
that no slot names takes nothing, so a forgotten `[pool.music]` can't make the players disappear from the device;
`check-config` says "pool music is on no slot".

`auto` stays what it is: the people and the applications that no channel and no pool of your own took.

## How a slot is filled

The resolver already hands members out in rounds, by kind (`slots/resolver.py`, `_contest`): per kind the slots that
take it, each kind from its side, and a slot that two kinds could fill goes to the one higher in its stack. This page
keeps those rules and changes what a "kind" is: today it is one of `people`, `apps`, `devices`, in future it is a
**source**, and every pool of your own is one.

- **Chain and hand-down** are unchanged: a pool with no member for a slot hands it to the candidate below it (a pool or
  `-`). A pool of your own is a pool in a chain like the others, and may be above or below any of them. The rule that
  channels end a chain stays.
- **Contest.** A slot named by several sources goes to the source higher in its stack; a tie goes to the order of
  [What it takes](#what-it-takes) (your pools before the built-in ones). The loser gives the slot up and hands out
  again, until nothing changes. It ends for the same reason as today: a source only loses slots.
- **Fill order.** Each source from its side. The people of a pool of people first take the slots where it is the first
  candidate ([Not a block](people.md#not-a-block)); a pool of applications keeps the slot each had.
- **Pins and `pick`.** A pool of applications has `encoder = "pick"` by default like `apps`. The pin is per slot and
  names the member, so it works across pools unchanged; the members `pick` offers are those of the pool the slot's
  chain reaches first (paused ones too).
- **Waiting.** Members that got no slot wait **per source**: `Result.waiting` keys are pool names, so `why` and the GUI
  say "Alice waits" for `friends` and "Spotify waits" for `music`.
- **Presence.** `present` of a pool of your own is true while it has a member (an application plays, a listed person is
  in the voice chat), counted before slots are assigned, like the built-in pools.

## Hold, absence and reload

`hold` and `absent_after` become per source: `PoolMembers` (`slots/inputs.py`) keeps one `Lingering` list per pool of
your own, not one for `apps`. A reload carries them over by pool id (`carry`); a pool that is gone drops its list.

## In the daemon

| Where | Change |
|---|---|
| `slots/model.py` | `PoolConfig` becomes a union on `kind`: channels (no `kind`), `apps`, `people`. `Scene` knows the pools of your own, their order, their members' rules (`match`, `people`) and their look. The names `apps`, `people`, `auto`, `devices` stay reserved. |
| `slots/inputs.py` | Membership by the order above; `PoolMembers` per pool; `pool_present` for the new kinds. |
| `slots/resolver.py` | `KINDS`, `ORDER`, `kind_of`: from three constants to the sources of the scene. `Shown.pool` is the pool of your own; `Result.waiting` keys likewise. |
| `slots/outcomes.py`, `why.py`, `simulation.py` | The table of `check-config` and Simulate count presence of the new pools; the notes say "pool X is on no slot" and "pool X can never show" (like a channel below a pool). Simulate gets counts for the members of each pool of your own, as for `apps` and `people`. |
| `runtime/slots.py`, `strips/` | A strip for a member of a pool of your own is built like one of `apps` or `people`, with the look of its pool. |
| `live/messages.py`, `mqtt.py` | `SlotView.pool` carries the pool id; the HA sensor `sensor.<ns>_slot_<n>` shows `app:<name>` / `person:<name>` as before, with the pool in its attributes. |
| GUI | The Channels page gets "Pool of applications" and "Pool of people" in its Add menu and a form per kind (`match`, `exclude` or `people`, the side, the look). The slot card's chip names the pool and the member (`music · Spotify`). |
| Docs | `configuration/slots.md` (pools), `channels/applications.md` and `people.md`, `concepts.md`, the example in `config.example.toml` stays small. |

## Use cases

Applications are listed in the order they started; `A`, `B` are people in the order of `people`.

### U1: music apart from the rest

`[pool.music] kind = "apps", match = ["@music"]`, `5 = ["music", "apps"]`, `6 = "apps"`.

| Plays | Slot 5 | Slot 6 |
|---|---|---|
| Firefox | Firefox | dark |
| Spotify | Spotify | dark |
| Firefox, Spotify | Spotify | Firefox |
| Spotify stops, `hold` passes (Firefox plays on) | dark | Firefox |

With only Firefox playing, `music` has no member and hands slot 5 down to `apps`, which fills from the left. When
Spotify comes, `music` takes slot 5 back and Firefox moves to slot 6, the one slot left for `apps`. Once Spotify is
gone, Firefox keeps slot 6 (applications keep their slot) and slot 5 goes dark: `apps` has no other member.

### U2: friends first

`[pool.friends] kind = "people", people = ["Alice", "Bob"]`, `6 = ["friends", "people"]`, `7 = ["people", "apps"]`.
In a call with Bob, Carol and Alice: slot 6 Alice (the first of the pool's own order), slot 7 Carol, Bob waits for
`friends`' second slot, which does not exist. Bob is not handed to `people` either: a member of a pool of your own
stays in it, so `why` says "Bob waits".

### U3: a pool above `auto`

`3 = ["music", "auto"]`: the players first, else the next application or person, as `["apps", "people"]` would. The
pool of your own wins a contest over `auto` on the same slot because it is higher in the stack.

## Decisions to confirm

1. **Members are kept in their pool** (U2): a person of `friends` who finds no slot waits, and does not fall into
   `people`. This keeps "who sits where" predictable and mirrors a channel with a slot. The alternative (fall through
   to the built-in pool when the slot's chain has one) gives Bob a slot, but then `friends` is no longer "the friends'
   strips".
2. **A pool of your own takes its members only while a slot names it.** The alternative, always taking them, hides
   applications silently.
3. **`kind = "devices"` is not offered.** The built-in `devices` pool has `exclude` already; a pool of devices of your
   own has no use case yet.
4. **No `order` in a pool of people.** The list of names is the order. Members of the built-in `people` pool that are
   not listed sit after, as today.
