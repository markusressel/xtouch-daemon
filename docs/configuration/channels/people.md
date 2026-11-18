# People and the voice chat

The people of the voice chat come from the provider of [`[voip]`](#voice-chat) (by default the Mumble plugin). They
sit on the slots that show the pool `people`, and share the slots of `auto` with the applications: people from the
right, in their order, applications from the left (see [Where people sit](#where-people-sit)). Someone who should
always have a strip of their own gets a [`person` channel](#strips-for-one-person).

```toml
[pool.people]
from = "right"              # the side they fill their slots from
color = "white"
talking_color = "green"
order = ["Alice", "mum"]    # these first, then the others as they came

[slots]
5 = ["people", "apps"]      # a person, else an application
6 = ["people", "apps"]

[channel.mum]
type = "person"
person = ["Alice", "alice-phone"]   # the same person, from the desk or the phone
label = "Mum"
```

## The strips of people

`[pool.people]` has the look of the strips of people without a channel of their own, a `person` channel has the
same options:

| Option | Default | Meaning |
|---|---|---|
| `label` | the first name of `person` | The top line of a `person` channel; people without a channel show their name. |
| `color` | `"white"` | The backlight while the person is there and does not talk. Dark while they are away. |
| `talking_color` | `"green"` | The backlight while the person talks. |
| `meter` | `true` | Whether the LED meter shows the person's voice. Without levels from the provider it lights while they talk. |
| `meter_point` | `behavior.meter_point` | `"pre_fader"`: their voice before the volume of their fader; `"post_fader"`: after it, see [Meters](index.md#meters). |
| `max_volume` | `behavior.max_volume` | The volume of a person with the fader at the top, 1..200 percent; 100 % is at the 0 dB mark as on the other strips. Above 100 % the voice is louder than Mumble plays it, and may clip. |

The strips of people have no `launch`: starting the voice chat is a control of a slot, e.g.
`7 = { select = { launch = ["mumble"] }, when = "not call" }` in [`[controls]`](../slots.md#controls-and-the-chord).
A place of `people` in a slot takes `color`, `meter` and `meter_point`: `{ show = "people", color = "orange" }`.

## Where people sit

| Option of `[pool.people]` | Default | Meaning |
|---|---|---|
| `from` | `"right"` | The side the people fill their slots from: `"right"` slot 8 first, `"left"` slot 1 first. Also inside `auto`. |
| `order` | none | Who sits first: names, or ids of `person` channels. Then the others in the order the daemon first saw them (it remembers that order for 30 days, across restarts). |

- People sit on the slots whose candidate `people` or `auto` wins, in their order. They keep no slot: when someone
  earlier in the order comes, the others move one slot on.
- They take the slots where nothing is above them in the stack first, then the others: a slot that a candidate above
  can take back (`voip if call`) would move every one of them.
- A slot `people` has no one for goes to the pool right below it: `["people", "apps"]` shows the next application.
  A slot of `auto` takes a person before an application; on `["apps", "people"]` the application comes first.
- More people than slots: the others wait, `xtouch-daemon why people` says who.
- `"people if call"` shows people only while `call` is on; `present(people)` holds while anyone of them is in the
  voice chat. Slots that should never show people say `apps` instead of `auto`.

The top line shows the name, the bottom line `muted`, the volume while the fader moves, or `talks`. The fader sets
the person's volume and Mute mutes them for you, if the provider can. The daemon remembers the volume and the mute it
set for each name while it runs, and sets them again when that person comes back (the voice chat starts them at
100 % otherwise). A mute changed in the voice chat itself (Mumble's local mute) replaces the one it set.

## Strips for one person

A `person` channel always shows that person, on the slots that name it. The names are the names in the voice chat,
ignoring case, but otherwise exactly (no wildcards, no parts of a name). With several names, the first person of the
provider's order with one of them is on the strip.

While the person is not in the channel, the strip shows the name dark, `away` on the second line and its fader at
the bottom; `"mum if present"` in a slot shows the channel only while they are there. The volume and mute the strip
set stay with the name while they are away and come back with them. A `person` channel without a slot is one of
the people (of `people` and `auto`) as itself; `in_pool = false` keeps it out.

## Voice chat

`[voip]` says where the people come from:

| Option | Default | Meaning |
|---|---|---|
| `provider` | `"bridge"` | `bridge`: a plugin of the voice chat client sends them (see below). `demo`: people who are not there and talk in turns, to try the strips of people. |
| `participants` | `["Alice", "Bob", "Carol", "Dave", "Eve"]` | The names of the `demo` people. |

Without the section, its defaults apply. None of the voice chat clients tells another program the volume of each
person, so the daemon can't read them from PipeWire: they all come out of one stream. Mumble has a
plugin API that can, and the bridge is what such a plugin talks to. For Mumble there is one: see
[Mumble](../../guides/mumble.md), which the GUI installs with a click. Other clients, TeamSpeak included, are not
supported yet; open an issue if you need one.

The state `voice_chat = true` (see [States and modes](../slots.md#states-and-modes)) is on while you are in a channel of
the voice chat.

A plugin for another client speaks the [bridge protocol](../../reference/voice-chat-bridge.md).

Next: [Mumble](../../guides/mumble.md) for the plugin, [slots](../slots.md#pools-of-applications-and-of-people) for pools of people of your own.
