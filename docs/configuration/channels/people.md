# People and the voice chat

A strip can show a person of your voice chat (Mumble or TeamSpeak): their name, whether they talk, and a fader for
how loud you hear them. The people come from a plugin in the voice chat client, see [Voice chat](#voice-chat).

There are two ways to put people on strips:

- The pool `people` hands out the people in the voice chat that no `person` channel with a slot shows, one person per slot. The pool `auto` hands out the
  same people and the applications that play (see [Applications](applications.md#apps-and-auto)). The people fill
  the free slots of `auto` from the right, in their order. The applications fill them from the left, so the two
  meet in the middle. See
  [Where people sit](#where-people-sit).
- A [`person` channel](#strips-for-one-person) is for someone who should always have a strip of their own.

In this example, `[pool.people]` sets how everyone without a channel looks and in which order they sit (Alice first,
then the others as they came). Slots 5 and 6 show a person, else an
application. `mum` is a `person` channel, and slot 4 shows it:

```toml
[pool.people]
from = "right"              # the side they fill their slots from
color = "white"
talking_color = "green"
order = ["Alice", "Bob"]    # names in the voice chat: these sit first, then the others

[slots]
4 = "mum"                   # this strip is always Mum
5 = ["people", "apps"]      # a person, else an application
6 = ["people", "apps"]

[channel.mum]
type = "person"
person = ["Mum", "mum-phone"]   # the same person, from the desk or the phone
label = "Mum"
```

## The strips of people

The look of the strips of people is set in `[pool.people]` (for everyone without a channel of their own) or in a
`person` channel (for that person). Both take these options:

| Option | Default | Meaning |
|---|---|---|
| `label` | the first entry of `person` | The top line of a `person` channel; people without a channel show their name. |
| `color` | `"white"` | The backlight while the person is there and does not talk. On a `person` channel, dark while they are away. |
| `talking_color` | `"green"` | The backlight while the person talks. |
| `meter` | `true` | `false` turns the LED meter off. The meter shows the voice of the person. If the plugin sends no levels, it lights while they talk. |
| `meter_point` | `behavior.meter_point` | `"pre_fader"`: their voice before the volume of their fader; `"post_fader"`: after it, see [Meters](index.md#meters). |
| `max_volume` | `behavior.max_volume` | The volume of a person with the fader at the top, 1..200 percent; 100 % is at the 0 dB mark as on the other strips. Above 100 % the voice is louder than the voice chat client plays it, and may clip. |

The strips of people have no `launch` option. To start the voice chat client, give a slot a control instead, for example
`7 = { select = { launch = ["mumble"] }, when = "not call" }` in [`[controls]`](../slots.md#controls-and-the-chord)
(`call` is a [state](../slots.md#states-and-modes) you define, for example `[state.call]` with `voice_chat = true`).
A place of `people` in a slot takes `color`, `meter` and `meter_point`: `{ show = "people", color = "orange" }`.

## Where people sit

| Option of `[pool.people]` | Default | Meaning |
|---|---|---|
| `from` | `"right"` | The side the people fill their slots from: `"right"` slot 8 first, `"left"` slot 1 first. This holds for the slots of `people` and for the people on the slots of `auto`. The side of the applications is `from` in `[pool.apps]`. |
| `order` | none | Who sits first: names, or ids of `person` channels. Then the others in the order the daemon first saw them (it remembers that order for 30 days, across restarts). |

- People sit on the slots that show `people` or `auto`, one person per slot, in their order. A person has no fixed
  slot. Every time the voice chat changes, the daemon sits everyone again. Say `from = "right"`, Alice is first in
  `order`, and Bob is on slot 8. When Alice joins, she takes slot 8 and Bob moves to slot 7.
- Some slots hold a condition above `people`, for example `["voip if call", "people", "apps"]`. While `call` is on,
  `voip` is shown there and no person sits there. People sit first on the slots where `people` or `auto` is the first
  candidate. They use a slot with a condition above them, like `["voip if call", "people", "apps"]`, only when the
  others are full. This keeps
  the people from jumping to another slot each time `call` turns on or off.
- When `people` has no one for a slot, the slot shows the next candidate: `["people", "apps"]` shows the next
  application. A slot of `auto` takes a person before an application. In `["apps", "people"]` the application comes
  first.
- With more people than slots, the others wait. `xtouch-daemon why people` says who.
- Conditions can ask about people. `"people if call"` shows people only while the state `call` is on. `present(people)`
  holds while anyone is in the voice chat (`present(<channel or pool>)` is a part of conditions, see
  [Conditions](../slots.md#conditions)). To keep people off a slot,
  write `apps` there instead of `auto`.

The top line shows the name, the bottom line `muted`, the volume while the fader moves, or `talks`. The fader sets
the person's volume and Mute mutes them for you, if the provider can. The daemon remembers the volume and the mute it
set for each name while it runs, and sets them again when that person comes back (it forgets them when the
daemon stops). Without this, the voice chat starts
everyone at 100 %. If you change a mute in the voice chat itself (Mumble's local mute), that mute replaces the one
the daemon set.

## Strips for one person

A `person` channel always shows that person, on the slots that name it. The names are the names in the voice chat,
ignoring case, but otherwise exactly (no wildcards, no parts of a name). With several names (the same person from the desk and from the phone), the strip shows the first of them that is in the voice chat,
in the order the voice chat client lists its people.

While the person is not in the channel, the strip shows the name with a dark backlight, `away` on the second line and its fader at
the bottom; `"mum if present"` in a slot shows the channel only while they are there. The volume and mute the strip
set stay with the name while they are away and come back with them. A `person` channel that no slot names is still handed out by the pools `people` and `auto`, as one of the people, with
its own look; `in_pool = false` keeps it out.

## Voice chat

`[voip]` says where the people come from:

| Option | Default | Meaning |
|---|---|---|
| `provider` | `"bridge"` | `bridge`: a plugin of the voice chat client sends them (see below). `demo`: people who are not there and talk in turns, to try the strips of people. |
| `participants` | `["Alice", "Bob", "Carol", "Dave", "Eve"]` | The names of the `demo` people. |

Without the section, its defaults apply. The daemon can't read the voice of each person from PipeWire, because voice chat clients mix everyone into one
stream. So a plugin in the client must tell the daemon each person's level and set each person's volume. Mumble and TeamSpeak 3 have
plugin APIs that allow this, and the bridge is what such a plugin talks to. There is a plugin for each: see
[Mumble](../../guides/mumble.md), which the GUI installs with a click, and [TeamSpeak](../../guides/teamspeak.md).
Other clients, e.g. Discord, are not supported yet; open an issue if you need one.

The state `voice_chat = true` (see [States and modes](../slots.md#states-and-modes)) is on while you are in a channel of
the voice chat. With plugins of several clients connected, the strips show the people of all of them, and the state
is on while you are in a channel of any of them.

A plugin for another client speaks the [bridge protocol](../../reference/voice-chat-bridge.md).

Next: [Mumble](../../guides/mumble.md) or [TeamSpeak](../../guides/teamspeak.md) for the plugin, [slots](../slots.md#pools-of-applications-and-of-people) for pools of people of your own.
