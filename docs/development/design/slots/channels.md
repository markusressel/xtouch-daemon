# Channels and pools

Part of [Design: channels, states and slots](index.md).

## Channels: what a strip controls

A channel is the old strip without its place: `type` and the options of that type. The table key is its id.

```toml
[channel.out]
type = "output"
color = "cyan"

[[channel.out.choices]]
label = "Phones"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:analog-stereo+input:analog-stereo"

[[channel.out.choices]]
label = "Buds"
device = "bluez_output.*"

[channel.spotify]
type = "apps"
match = ["spotify"]
tags = ["media"]

[channel.alice]
type = "person"
person = ["Alice", "alice-phone"]
label = "Mum"
```

- **Types**: `output`, `input` ([choices](../choices.md)), `apps`, `homeassistant`, and `person` (one person of the
  voice chat, with `talking_color`, `max_volume`, `meter`). Two `person` channels with a name in common are an error.
  A deliberately empty slot is the candidate `"-"`.
- **`tags`**: free-form names for grouping channels, used by pools (`#media`) and the `channels` source of states.
  They are no conditions; name them after what the channels are (`media`, `games`), not after states.
- **Presence**: whether the channel has something to control: its device is there, an application of the group has a
  stream, the person is in the voice chat; always for `homeassistant`. `absent_after` (default
  `behavior.absent_after`, 3 s) delays "absent", so a reconnecting Bluetooth device does not flap; it is present again
  at once.
- **`in_pool`** (default `true`, `apps` and `person` channels): whether the channel joins the pools while it is present
  and no slot shows it: an `apps` channel `apps` and `auto` (as a whole: its label, volume and entities, as in DAW
  banking), a `person` channel `people` and `auto` (as itself).
- **Its entities** are named by its id (`select.xtouch_out_output`), the same wherever and whenever it shows, and stay
  available while it is not shown. One owner per stream: the channel, wherever it is.

## Pools: one of several

A pool gives each slot that shows it one **member** that no other slot shows.

| Pool | Members | Options |
|---|---|---|
| `apps` | The applications that play and have no channel, and the present `apps` channels with `in_pool` that have no slot. In the order they started playing; a member stays one `hold` seconds after it stopped. | `[pool.apps]`: `from` (`"left"`), `exclude` (never these), `hold` (5 s), the look of the strips of applications. |
| `people` | The people in the voice chat without a `person` channel, and the present `person` channels with `in_pool` that have no slot. In `order`, then as first seen. See [Where the people sit](people.md). | `[pool.people]`: `from` (`"right"`), `order`, the look of the strips of people (`color`, `talking_color`, `meter`, `meter_point`, `max_volume`). |
| `auto` | Both: people and applications share its slots, the people first, each from its side. | `[pool.auto]`: the look of the strips of applications on its slots. |
| `devices` | The outputs and inputs that no `output` or `input` channel has (a USB headset). `auto` doesn't take them. | `[pool.devices]`: `from`, `exclude` (node names or descriptions, wildcards), `hold`, the look. |
| `[pool.<id>] channels = [...]` | The present channels of the list (ids, `"#tag"`) that have no candidate of their own that shows, in the list's order. | `channels`, `from`. Its members bring their own look. |

- **Presence of a pool**, for `if present`, counts its members before slots are assigned: `apps` while an application
  it may take plays; `people` while someone who would be one of them is in the voice chat (also a `person` channel
  with a slot of its own); `auto` while either is; `devices` while a device without a channel is there; a pool of
  channels while one of them is present.
- **`from`** is `"left"` (slot 1 first) or `"right"` (slot 8 first). Inside `auto` the people fill from
  `[pool.people] from`, the applications from `[pool.apps] from`. The defaults are opposite sides, so people and
  applications meet only when the slots run out.
- **Members keep their slot** in `apps` and `auto`, so applications don't hop around. People sit in their order
  instead, and a pool of channels fills by its order (the first present channel gets the first slot): Buds coming back
  takes its place, the others move on.
- **Members are typed**: an application, a channel or a person, never told apart by their names (someone called
  `browser` is no channel). People are told apart by the voice chat's id of the participant; `order` and the learned
  order go by name.
- **Select** does what it does on the member (makes a device the default, launches).
- **Pick** (the `pick` encoder of a slot of `apps` or `auto`): turning picks the slot's member among the applications
  without a slot (`2/5`; people are never picked); a push pins it, and it stays on the slot after it stopped playing,
  until the next push. A pin beats the pool's order, and people don't take a pinned slot. The resolver keeps the
  pins: the encoder only asks for one.
- **Channels of a pool without a slot don't wait**: only applications and people do; such channels are not shown.
