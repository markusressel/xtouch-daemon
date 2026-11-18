# Design: where the people of the voice chat sit

Status: decided (2026-11-17), being built. Round 3: option D of round 2 with three built-in pools. It replaces
decisions 1 and 7 of [Decisions after the live test](channels-states-slots.md#decisions-after-the-live-test) and the
parts of [People](channels-states-slots.md#people) that place people.

## Why

Until now the people of the voice chat had no candidate of their own: the resolver put them on the slots of `auto`,
from the right, while applications filled them from the left. That fits one layout (the voice chat's strips on the
right) and the file could not say anything else: not the voice chat on the left, not people in the middle, not
people only in a call, not "a call replaces the applications". The GUI didn't show that `auto` takes people at all.

## The format

Three built-in pools. Each is a candidate like any channel or pool:

| Pool | Members | Section and options |
|---|---|---|
| `apps` | The applications that play and have no channel, and the `apps` channels with `in_pool` that play and have no slot (as a whole). | `[pool.apps]`: `from` (default `"left"`), `exclude` (default `["speech-dispatcher"]`), `hold` (default 5), the look of the strips of applications on its slots. |
| `people` | The people in the voice chat without a `person` channel, and the `person` channels with `in_pool` that are present and have no slot (as themselves). In `order`, then as first seen (learned, kept 30 days). | `[pool.people]`: `from` (default `"right"`), `order`, the look of the strips of people (`color`, `talking_color`, `meter`, `meter_point`, `max_volume`). |
| `auto` | Both: people and applications share its slots, the people first. | `[pool.auto]`: the look of the strips of applications on its slots. People look as `[pool.people]` says. |

```toml
[pool.people]
from = "right"              # the side the people fill their slots from (the default)
order = ["Alice", "mum"]
color = "yellow"

[pool.apps]
from = "left"               # the default
hold = 5
exclude = ["speech-dispatcher", "notification"]

[channel.mum]
type = "person"
person = ["Alice", "alice-phone"]
in_pool = true              # while no slot shows mum, she is one of the people (default)

[slots]
4 = ["people", "apps"]      # a person, else an application
5 = ["people", { show = "apps", encoder = "pick" }]
6 = [{ show = "people", color = "orange" }, "apps"]
```

- A slot without an entry is `auto`, and a stack that can run out ends in `auto`, as before. The simple case needs
  no words: people from the right, applications from the left, on every slot.
- `from` is `"left"` (slot 1 first) or `"right"` (slot 8 first). It is an option of `apps`, `people` and the pools of
  channels; inside `auto` the people fill from `[pool.people] from`, the applications from `[pool.apps] from`. The
  defaults are opposite sides, so people and applications meet only when the slots run out. (Round 2 proposed
  `"left"` for every pool; with people inside `auto` that would make every person push the applications along.)
- `in_pool` (default `true`) replaces `in_auto`: an `apps` channel without a slot goes into `apps` and `auto`, a
  `person` channel without a slot into `people` and `auto`.
- Places: a place of `apps` takes the options of an `auto` place (the look, `encoder`, `min_volume`, `max_volume`);
  a place of `people` takes `color`, `meter` and `meter_point` (people show their names and have no Rec or Solo of
  a place).
- Presence: `present(apps)` while an application `apps` may take plays; `present(people)` while someone who would
  be one of the people is in the voice chat (counted before slots, so also a `person` channel with a slot of its
  own); `present(auto)` while either is.

## The rules

Step 1 (fixed slots) and step 2 (channels by rank) stay as they are. Step 3 hands out the members of the pools.

1. **Chain.** The pool a slot shows after step 2 and the candidates below it that hold while they are pools, up to
   and with a `-`, form the slot's chain. A channel ends it. `["people if call", "- if call", "auto"]` while `call`
   is on: `people`, `-`.
2. **Hand-down.** A pool with no member for a slot leaves it to the next pool of the chain. A slot that no pool
   fills shows the last pool of its chain, dark, or `-`. (Before: a pool slot without a member was dark.)
3. **Pools of channels first**, in the order of the file, each from its side. A pool of channels below `apps`,
   `people` or `auto` in a chain is an error: those take the channels that no pool of channels gives a slot.
4. **Contest.** Then the people and the applications are handed out: the people over the slots whose chain has
   `people` or `auto`, in their order; the applications over those with `apps` or `auto`, pins first, then each on
   the slot it had, then in their order. A slot both fill goes to the one higher in its stack (inside `auto`, the
   people). The other gives that slot up and is handed out again, until nothing changes. It ends: each only loses
   slots. Members left over wait (`waiting["people"]`, `waiting["apps"]`).
5. **Fill order.** Each from its side. The people first take the slots where they are the first candidate, then
   the others.

### Not a block

People inside `auto` (and in `people`) are **no block**: they take the slots where nothing is above them first,
then the others, each group from their side. In the live test's file with `call` overridden off the order was
6, 5, 4, then 8, 7, 3, 2. This stays, for a reason: people keep no slot (they sit in their order, recomputed every
step), so a slot that a candidate above can take back (`voip if call`) would move every one of them when it does.
Applications keep the slot they had, so for them the side alone decides (as before: slot 2 before slot 3, whatever is
above them).

### Pins, held slots, `hold`

- A pin (the `pick` encoder) is an application's; it reserves its slot if the chain there has `apps` or `auto`.
  People don't take a pinned slot. People are never picked or pinned.
- What a held or dwelling slot shows, of any pool, is not handed out again.
- `hold` keeps an application a member after it stopped; `absent_after` keeps a person one after they left.

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

## The GUI

- **Slots**: Shows offers `apps`, `people` and `auto` with the channels. The dot is on the candidate that fills the slot
  (on `people` while a person sits there). A pool without a condition reads `when app without a slot → apps` (an outlined chip)
  (tooltip: what a member needs, e.g. an application that plays and has no slot yet; revised 2026-11-18, it read `left
  over → apps` below another pool). A tiny LCD after each candidate has the color of its strip. The inspector says what
  a pool hands out and from where (`Pool people: the people of the voice chat ..., from the right.`), with the place
  options of its strips: those of an application for `apps` and `auto`, of a person for `people`, of a channel for a
  pool of channels.
- **Simulate**: two counts next to the states, people in the call and applications that play; the device shows their
  names. `apps fill` and `people fill` are what-ifs where the stacks name them.
- **Grid**: `apps` and `people` are dimensions where a stack names them (full: as many as slots), e.g. a row
  `call, people fill`.
- **Channels**: the built-in pools `[pool.apps]`, `[pool.people]` and `[pool.auto]` below the channels, each with its
  options and the look of its strips.
- **why**: `xtouch-daemon why people` lists who sits where and who waits; a slot's why says `people: none left for
  this slot` when it was handed down.

## Built

| Part | Where |
|---|---|
| Pools, options, errors, chain check | `slots/model.py` (`AppsConfig`, `PeopleConfig`, `AutoConfig`, `PoolConfig`, `_parse_pools()`, `_check_chains()`, `place_options()`) |
| Presence, members | `slots/inputs.py` (`pool_present()`, `people_of()`, `excluded()`) |
| Chains, hand-down, contest | `slots/resolver.py` (`_chain()`, `_of_channels()`, `_contest()`, `_fill_order()`) |
| Simulate, Grid, notes | `slots/outcomes.py` (`simulate()` with counts, `dimensions()`, `notes()`), `cli/configuration.py` |
| Strips of places | `config/slots.py`, `runtime/binder.py` (people take the look of their place) |
| GUI | `gui/domain/slot_stacks.py`, `gui/domain/simulate.py`, `gui/domain/channels.py`, `gui/qt/pages/slots.py`, `gui/qt/pages/channels.py` |

Tests are Markus's call; the existing ones that describe the old rules fail as expected (`in_auto`, `[people]`,
`hold` of `[pool.auto]`, `waiting["auto"]`, a pool of channels that was dark and now hands down).

## Not chosen

- **People only as a pool, pools never fall through**: slots meant for people are dark outside a call (the live test
  rejected that).
- **`auto` alone with options in `[people]`** (`from`, `slots`, `when`, `alone`): a second language next to the stacks.
- **A preference per `auto` place** (`people = "first"`): the same as stacks, hidden in an option.
- **A list of slots for people** (`[people] slots = [6, 5, 4]`): a second place to edit when a slot moves.
- **A real block, or "first candidate first" for applications too**: see [Not a block](#not-a-block).
- **`+2` or paging when more people than slots**: they wait; the why line and the live view say who.
