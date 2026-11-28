# Where the people sit

Part of [Design: channels, states and slots](index.md). Status: built (2026-11-17), the third round of the design.
Its rules are in [Pools](channels.md#pools-one-of-several) and [the resolver](slots.md#the-resolver).

## Why

At first the people of the voice chat had no candidate of their own: the resolver put them on the slots of `auto`
from the right, while applications filled them from the left. That fits one layout (the voice chat's strips on the
right), and the file could say nothing else: not the voice chat on the left, not people in the middle, not people
only in a call, not "a call replaces the applications". The GUI didn't show that `auto` takes people at all.

So there are three built-in pools, each a candidate like any channel: `apps` (the applications), `people` (the
people) and `auto` (both, sharing its slots, the people first). A pool hands a slot it has no member for to the pool
or `-` right below it, so `["people", "apps"]` is a person, else an application.

## Not a block

People inside `auto` (and in `people`) are **no block**: they take the slots where nothing is above them first,
then the others, each group from their side. In the live test's file with `call` overridden off the order was
6, 5, 4, then 8, 7, 3, 2. This stays, for a reason: people keep no slot (they sit in their order, recomputed every
step), so a slot that a candidate above can take back (`voip if call`) would move every one of them when it does.
Applications keep the slot they had, so for them the side alone decides (as before: slot 2 before slot 3, whatever is
above them).

## Use cases

`A`, `B`, ... are people in their order; "call" is the state `call` (Mumble: `voice_chat = true`). The tables come
from the resolver (without a previous result).

### U1: voice chat on the right (Markus)

```toml
[pool.people]
color = "yellow"

[pool.apps]
color = "white"

[slots]
1 = "main"
2 = ["browser if present", "apps", "people"]
3 = ["game if present", "apps", "people"]
4 = ["people", { show = "apps", rec = "recording" }]
5 = ["people", "apps"]
6 = ["people", "apps"]
7 = ["voip if call", "apps"]
8 = ["mic if call", "apps"]
```

| Situation | 2 | 3 | 4 | 5 | 6 | 7 | 8 | Waits |
|---|---|---|---|---|---|---|---|---|
| No call, nothing plays | people | people | apps | apps | apps | apps | apps | |
| No call, browser and Spotify play | browser | Spotify | apps | apps | apps | apps | apps | |
| Call, 1 person | people | people | apps | apps | A | voip | mic | |
| Call, 3 people | people | people | C | B | A | voip | mic | |
| Call, 3 people, browser and Spotify play | browser | Spotify | C | B | A | voip | mic | |
| Call, 7 people | E | D | C | B | A | voip | mic | F, G |
| Call, 7 people, browser and Spotify play | browser | Spotify | C | B | A | voip | mic | D, E, F, G |

On 2 and 3 applications come before people: in a crowded call a playing application still gets a fader. A dark
slot shows the last pool of its chain (`people` on 2 and 3).

### U2: mirrored (voice chat on the left)

```toml
[pool.people]
from = "left"

[pool.apps]
from = "right"

[slots]
1 = ["mic if call", "apps"]
2 = ["voip if call", "apps"]
3 = ["people", "apps"]
4 = ["people", "apps"]
5 = ["people", "apps"]
6 = ["game if present", "apps", "people"]
7 = ["browser if present", "apps", "people"]
8 = "main"
```

| Situation | 1 | 2 | 3 | 4 | 5 | 6 | 7 | Waits |
|---|---|---|---|---|---|---|---|---|
| No call, browser plays | apps | apps | apps | apps | apps | people | browser | |
| Call, 1 person | mic | voip | A | apps | apps | people | people | |
| Call, 3 people, browser and Spotify play | mic | voip | A | B | C | Spotify | browser | |
| Call, 7 people | mic | voip | A | B | C | D | E | F, G |

### U3: people in the middle

```toml
[pool.people]
from = "left"

[pool.apps]
from = "right"

[slots]
1 = "main"
2 = "apps"
3 = ["people", "apps"]
4 = ["people", "apps"]
5 = ["people", "apps"]
6 = ["people", "apps"]
7 = "apps"
8 = "mic"
```

| Situation | 2 | 3 | 4 | 5 | 6 | 7 | Waits |
|---|---|---|---|---|---|---|---|
| No call, X, Y, Z play | apps | apps | apps | Z | Y | X | |
| Call, 1 person, X plays | apps | A | apps | apps | apps | X | |
| Call, 3 people, X, Y, Z play | Z | A | B | C | Y | X | |
| Call, 4 people, X, Y, Z play | Y | A | B | C | D | X | Z |
| Call, 7 people | apps | A | B | C | D | apps | E, F, G |

Applications fill from the right, so slot 2 comes last; `from` is a side, not "the edges first".

### U4: people only in a call

Matters when `call` means less than "someone is in the voice chat", e.g. sitting in a Mumble lobby all evening with
`call` toggled by a button. Slots that should never show people say `apps`: `auto`, also the implicit one at the end
of a stack that can run out, takes people.

```toml
[slots]
1 = "main"
2 = "apps"
3 = "apps"
4 = ["people if call", "apps"]
5 = ["people if call", "apps"]
6 = ["people if call", "apps"]
7 = ["voip if call", "apps"]
8 = ["mic if call", "apps"]

[controls]
8 = { solo = "toggle:call" }
```

| Situation | 2 | 3 | 4 | 5 | 6 | 7 | 8 | Waits |
|---|---|---|---|---|---|---|---|---|
| 3 people in the lobby, `call` off, Spotify plays | Spotify | apps | apps | apps | apps | apps | apps | A, B, C |
| `call` on, 3 people, Spotify plays | Spotify | apps | C | B | A | voip | mic | |
| `call` on, 3 people, Spotify and mpv play | Spotify | mpv | C | B | A | voip | mic | |

### U5: a call replaces the applications

```toml
[pool.people]
from = "left"

[slots]
1 = "main"
2 = ["people if call", "- if call", "auto"]
3 = ["people if call", "- if call", "auto"]
4 = ["people if call", "- if call", "auto"]
5 = ["people if call", "- if call", "auto"]
6 = ["people if call", "- if call", "auto"]
7 = ["voip if call", "auto"]
8 = ["mic if call", "auto"]
```

| Situation | 2 | 3 | 4 | 5 | 6 | 7 | 8 | Waits |
|---|---|---|---|---|---|---|---|---|
| No call, Firefox plays | Firefox | auto | auto | auto | auto | auto | auto | |
| Call, 1 person, Firefox plays | A | - | - | - | - | voip | mic | Firefox |
| Call, 3 people | A | B | C | - | - | voip | mic | |
| Call, 7 people | A | B | C | D | E | voip | mic | F, G |

### U6: the simple case

No entry, or `auto`: people from the right, applications from the left, on every slot that shows `auto`, as before.

## Errors and notes of `check-config`

| Where | Message |
|---|---|
| `[people]` | `people: the section is [pool.people] now; the people sit on the slots whose stack names people or auto` |
| `in_auto` | `channel.voip: in_auto is in_pool now` |
| `hold`, `exclude` in `[pool.auto]` | `pool.auto: hold: an option of [pool.apps] now` |
| `from`, `order`, `channels` in `[pool.auto]` | `pool.auto: from: auto fills from the sides of [pool.apps] and [pool.people]` (and the like) |
| `hold`, `exclude`, `channels` in `[pool.people]` | `pool.people: hold: people stay absent_after seconds after they left` (and the like) |
| `channels`, `order` in `[pool.apps]` | `pool.apps: order: an option of [pool.people]` (and the like) |
| `from` | `pool.people.from: Input should be 'left' or 'right'` |
| a channel or state named `apps`, `people` or `auto` | `channel.apps: apps is a built-in pool` |
| a place of `people` | `slots.6[0]: rec is no option of a place for people (...)` |
| a pool of channels below a built-in one | `slots.2[1]: media below auto: a pool of channels goes above the pools auto, apps and people` |

`check-config` prints notes after the table: a channel right below a pool without a condition never shows (a pool
hands down only to pools and `-`), and `people: no slot shows people or auto, ...` when the file has a `person`
channel or `[pool.people]` options and no slot can show people.

## Where it is

| Part | Where |
|---|---|
| Pools, options, errors, chain check | `slots/model.py` (`AppsConfig`, `PeopleConfig`, `AutoConfig`, `PoolConfig`, `_parse_pools()`, `_check_chains()`, `place_options()`) |
| Presence, members | `slots/inputs.py` (`pool_present()`, `people_of()`, `excluded()`) |
| Chains, hand-down, contest | `slots/resolver.py` (`_chain()`, `_of_channels()`, `_contest()`, `_fill_order()`) |
| Simulate, the outcome table, notes | `slots/outcomes.py` (`simulate()` with counts, `dimensions()`, `notes()`), `cli/configuration.py` |
| Strips of places | `config/slots.py`, `daemon/binder.py` (people take the look of their place) |
| GUI | `gui/domain/slot_stacks.py`, `gui/domain/simulate.py`, `gui/domain/channels.py`, `gui/quick/pages/slots.py`, `gui/quick/pages/channels.py` |

## Not chosen

- **People only as a pool, pools never fall through**: slots meant for people are dark outside a call (the live test
  rejected that).
- **`auto` alone with options in `[people]`** (`from`, `slots`, `when`, `alone`): a second language next to the stacks.
- **A preference per `auto` place** (`people = "first"`): the same as stacks, hidden in an option.
- **A list of slots for people** (`[people] slots = [6, 5, 4]`): a second place to edit when a slot moves.
- **A real block, or "first candidate first" for applications too**: see [Not a block](#not-a-block).
- **`+2` or paging when more people than slots**: they wait; the why line and the live view say who.
