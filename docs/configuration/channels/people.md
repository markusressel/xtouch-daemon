# People and the voice chat

A strip can show a person of your voice chat (Mumble or TeamSpeak): their name, whether they talk, and a fader for
how loud you hear them. The people come from a plugin in the voice chat client, see [Voice chat](#voice-chat).

There are two ways to put people on strips:

- The [pool](../slots.md#slots) `people` hands out the people in the voice chat that
  no `person` channel with a slot shows, one per slot. The pool `auto` hands out the same people and the
  [applications](applications.md#apps-and-auto): the people fill its free slots from the right, the applications
  from the left, so the two meet in the middle. See [Where people sit](#where-people-sit).
- A [`person` channel](#strips-for-one-person) is for someone who should always have a strip of their own.

Here `[pool.people]` sets how everyone without a channel looks and in which order they sit. Slots 5 and 6 show a
person, else an application. `mum` is a `person` channel, and slot 4 shows it:

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

`[pool.people]` (everyone without a channel) and a `person` channel (that person) take these options:

| Option | Default | Meaning |
|---|---|---|
| `label` | the first entry of `person` | The top line of a `person` channel; people without a channel show their name. |
| `color` | `"white"` | The backlight while the person is there and does not talk. On a `person` channel, dark while they are away. |
| `talking_color` | `"green"` | The backlight while the person talks. |
| `meter` | `true` | `false` turns the LED meter off. It shows the voice of the person, or lights while they talk if the plugin sends no levels. |
| `meter_point` | `behavior.meter_point` | `"pre_fader"`: their voice before the volume of their fader; `"post_fader"`: after it, see [Meters](index.md#meters). |
| `max_volume` | `behavior.max_volume` | The volume of a person with the fader at the top, 1..200 percent; 100 % is at the 0 dB mark as on the other strips. Above 100 % the voice is louder than the voice chat client plays it, and may clip. |

The strips of people have no `launch`. To start the voice chat client, use a control, see
[Launching the application](applications.md#launching-the-application). A place of `people` in a slot takes
`color`, `meter` and `meter_point`: `{ show = "people", color = "orange" }`.

## Where people sit

| Option of `[pool.people]` | Default | Meaning |
|---|---|---|
| `from` | `"right"` | The side the people fill their slots from: `"right"` slot 8 first, `"left"` slot 1 first. Holds for `people` and for the people on `auto`. The applications have `from` in `[pool.apps]`. |
| `order` | none | Who sits first: names, or ids of `person` channels. Then the others in the order the daemon first saw them (it remembers that order for 30 days, across restarts). |

- People need free slots: slots that show `people` or `auto`. A slot without an entry counts as `auto`, so it takes
  people too. They sit one per slot, in their order. A person has no fixed
  slot: every time the voice chat changes, the daemon sits everyone again. Say `from = "right"`, Alice is first in
  `order`, and Bob is on slot 8. When Alice joins, she takes slot 8 and Bob moves to slot 7.
- People sit first on the slots where `people` or `auto` is the first candidate. A slot with a condition above
  them, like `["voip if call", "people", "apps"]`, gets people only when the others are full. So people don't
  jump to another slot each time `call` turns on or off.
- When `people` has no one for a slot, the slot shows its next candidate. A slot of `auto` takes a person before an
  application; in `["apps", "people"]` the application comes first.
- With more people than slots, the others wait. `xtouch-daemon why people` says who.
- `present(people)` holds while anyone is in the voice chat, see [Conditions](../slots.md#conditions). To keep
  people off a slot, write `apps` there instead of `auto`.

The top line shows the name, the bottom line `muted`, the volume while the fader moves, or `talks`. The fader sets
the person's volume and Mute mutes them for you, if the provider can. The daemon remembers both for each name until
it stops and sets them again when that person comes back (the voice chat starts everyone at 100 %). A mute you
change in the voice chat itself replaces the one the daemon set.

## Strips for one person

A `person` channel always shows that person, on the slots that name it. The names are those in the voice chat,
ignoring case, but otherwise exact (no wildcards). With several names, the strip shows the first that is in the
voice chat, in the order the client lists its people.

While the person is not there, the strip shows the name with a dark backlight, `away` on the second line and its
fader at the bottom; `"mum if present"` in a slot shows the channel only while they are there. Their volume and mute
stay with the name. A `person` channel that no slot names is still handed out by the pools `people` and `auto`, with
its own look; `in_pool = false` keeps it out.

## Voice chat

`[voip]` says where the people come from:

| Option | Default | Meaning |
|---|---|---|
| `provider` | `"bridge"` | `bridge`: a plugin of the voice chat client sends them (see below). `demo`: people who are not there and talk in turns, to try the strips of people. |
| `participants` | `["Alice", "Bob", "Carol", "Dave", "Eve"]` | The names of the `demo` people. |

Voice chat clients mix everyone into one stream, so the daemon can't read each person's voice from PipeWire. A
plugin in the client tells the daemon each person's level and sets each person's volume. There is a plugin for
[Mumble](../../guides/mumble.md) (the GUI installs it with a click) and for [TeamSpeak](../../guides/teamspeak.md).
Other clients, e.g. Discord, are not supported yet.

The state `voice_chat = true` (see [States and modes](../slots.md#states-and-modes)) is on while you are in a voice
chat channel. With plugins of several clients connected, the strips show the people of all of them. A plugin for
another client speaks the [bridge protocol](../../reference/voice-chat-bridge.md).

Next: [Mumble](../../guides/mumble.md) or [TeamSpeak](../../guides/teamspeak.md) for the plugin, [slots](../slots.md#pools-of-applications-and-of-people) for pools of people of your own.
