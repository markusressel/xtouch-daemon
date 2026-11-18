# Design: channels, states and slots

Status: built (0.1.0). How to use it: [Channels, states and slots](../../../configuration/slots.md). How it came to be,
with the reviews and the live test: [History](../../history/slots.md).

The pages of this design:

- this one: the model, the names, the conditions, an example;
- [Channels and pools](channels.md): what a strip controls, and which one of several;
- [States and modes](states.md): when something matters;
- [Slots](slots.md): where it shows, the resolver, the controls of a slot;
- [Where the people sit](people.md): the pools `people`, `apps` and `auto`, with use cases;
- [In the daemon](daemon.md): the runtime, Home Assistant, the commands, the GUI.

## Why

A `[[strip]]` of the old format answered four questions at once, spread over several mechanisms:

| Question | Old format |
|---|---|
| **What** does it control? | `type` and its options. |
| **When** does it matter? | Implicitly, `collapse`, the rules of a `[[layout]]`. |
| **How** is it related to other strips? | `inherit` (by layout and position), the group of `voip` strips. |
| **Where** is it on the device? | Its position in a list, shifted by `collapse`, replaced as a whole by a layout. |

That made simple wishes hard: "VoIP and the Mic only during a call, else `auto` there" needed a group that collapses
together; a strip that matters while gaming and while calling needed two layouts that can't both be active; `inherit`
referred to "strip 6 of the layout default", so moving a strip changed its meaning; `collapse` moved every strip after
it, which hurts muscle memory.

## The model

Each concept answers one question and is edited in one place.

| Concept | Answers | Edited on |
|---|---|---|
| **Channel** | What a strip controls: a device, applications, a person in the voice chat, a Home Assistant strip. | Channels |
| **Pool** | Which one of several a strip takes: whatever plays and has no slot, the people in the voice chat, the next present channel of a list. | Channels |
| **State** | When something matters: a named on/off condition, live, with a manual override. A **mode** is a state that excludes the other modes. | States |
| **Slot** | Where: one of the 8 strips of the device, with a stack of candidates (channels or pools, each with a condition). | Slots |
| **Controls** | What a fader, encoder or button of a slot does whatever the slot shows (a Home Assistant knob, starting Mumble). | Slots |

### Names

Channels, pools, states and the `id`s of controls share one namespace: lower case letters, digits and `_`, unique
across all four (a control `id` names Home Assistant entities like a channel id does).

- Built in: the pools `auto`, `apps`, `people`, `devices`, and the mode `default`.
- Reserved: `and`, `or`, `not`, `if`, `present`, `none`, `mode`, and ids starting with `state_` or `slot_` (they would
  collide with entity ids in Home Assistant).
- Sigils: `@name` a [preset](../../../configuration/presets.md), `#name` a tag.

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
- `present`: the candidate's own channel or pool is present; only in candidates (a state takes channels with its
  source `channels`). `present(spotify)`: that channel or pool is.
- Errors point at the place: `slots.7[0]: "voip if cal": unknown state cal (did you mean call?)`, with a caret in the
  GUI and `check-config`.

Conditions depend only on **inputs**, states and presence, never on what other slots show (the presence of a pool is
counted before slots are assigned). That makes the resolver deterministic and Simulate truthful.

## An example

The author's configuration ([example.toml](example.toml); about 110 lines in the old format):

```toml
[channel.out]
type = "output"
color = "cyan"
choices = [ ... ]   # Phones, Speaker, Buds

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

What it shows, as `xtouch-daemon simulate docs/development/design/slots/example.toml --table` prints it (a test keeps
this table in line with the file): one row per combination of the states and presence the stacks ask about that
changes something.

```
when             1    2        3     4-6   7     8
default          out  browser  auto  auto  auto  auto
call             out  browser  auto  auto  voip  mic
gaming           out  browser  game  auto  auto  auto
gaming and call  out  browser  game  auto  voip  mic
```

- People share the `auto` slots: they sit from the right, next to VoIP, in their order; applications fill from the
  left. They meet only when the slots run out.
- With Mumble, joining a channel turns `call` on at once (`delay_on = 0`): VoIP, Mic and the person show up together.
  Leaving shows at once on the person's strip; VoIP and Mic stay 5 s, through a reconnect.
- Slot 4 sets an option of its strip, `rec` (here its default: the Rec LED shows recording).

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
