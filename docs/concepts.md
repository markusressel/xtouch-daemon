# Concepts

The few ideas the configuration is built from, and the words that look alike. Read this once before the
[configuration pages](configuration/index.md); the [Setup tour](getting-started/tour.md) puts them to work.

## The model in one example

```toml
[channel.buds]                    # a channel: what a strip controls
type = "output"
device = "bluez_output.*"         # any Bluetooth headphones
label = "Buds"

[channel.game]
type = "apps"                     # another channel: all streams of some applications
match = ["@steam-games"]
label = "Game"

[state.gaming]                    # a state: when something matters
mode = true                       # a mode: one of these at a time
processes = ["@steam-games"]

[slots]                           # a slot: what one strip of the device shows, top candidate first
1 = ["buds if present", "auto"]   # the buds while they are connected, else the next application that plays
2 = ["game if gaming", "auto"]    # the game while the mode gaming is on, else the next application
```

Strips 3 to 8 have no entry, so each shows `auto`. Everything else in this documentation refines one of these
parts.

## Strips and slots

The device has 8 **strips**, each with a fader, an [encoder](configuration/strip/encoders.md), a display (LCD), a meter and four buttons (Rec, Solo,
Mute, Select). A strip is hardware. A **slot** is the entry of the configuration for one strip, numbered 1 to 8 from
the left. A slot decides what its strip shows.

## Channels

A **channel** is a thing you define in the file and give one strip: a sound device, a group of applications, a person
of the voice chat, or a strip for [Home Assistant](guides/home-assistant.md). Its `type` says which:

| `type` | The strip controls |
|---|---|
| `output`, `input` | One sound device, one of several (`choices`), or the default one. |
| `apps` | All playback streams of a group of applications at once: one fader sets all of them. |
| `person` | One person of the voice chat. |
| `homeassistant` | Nothing by itself: its fader, encoder, display and buttons are entities in Home Assistant. |

A channel has an id (`buds`, `game`) that names it in slots, conditions and Home Assistant. It takes a strip only
when a slot names it.

Applications are controlled on the playback side only. An `apps` channel sets the volume of what an application
plays. What an application records is only observed: it lights the Rec LED and can turn on a state (see below), but
no fader or Mute acts on it.

## Slots

A slot is a list of **candidates**, top first. It shows the first candidate whose condition holds:

```toml
[slots]
3 = ["game if gaming", "auto"]    # the game in the mode gaming, else the next application
4 = "mic"                         # a single candidate: always the microphone
5 = ["game if gaming", "-"]       # the game in the mode gaming, else a dark strip
```

A candidate is a channel or pool name, optionally followed by `if` and a **condition**; `-` is nothing (the strip
goes dark). A slot without an entry is `auto`. Only the slots whose candidate changes move; the others stay as they
are, and a strip you are touching keeps what it shows until you let go.

## States and modes

A **state** is on or off. It is on while any of its sources is: an application plays or records, you are in the voice
chat, a process runs, a device is there, or Home Assistant says so. Slots ask about states in their conditions
(`game if gaming`).

A **mode** is a state with `mode = true`. One mode at a time is on, the one with the highest `priority`; without any,
the mode is `default`. A new mode shows its name across all displays for a moment. Modes can also be picked by hand:
the chord, `xtouch-daemon mode`, a button or Home Assistant.

## Conditions

A condition is the text after `if`: names of states and modes joined with `and`, `or`, `not` and parentheses, plus
`present`. A channel is **present** while it has something to control: an application of an `apps` channel plays, its
device is there, the person is in the voice chat. `"buds if present"` shows the buds only while they are connected.

## Pools

A **pool** supplies members that you don't list one by one. Each slot that names the pool gets the next member, so one
pool can fill several strips: the next application that plays, the next person in the voice chat. A channel is the
opposite: you define it, and it takes exactly one strip, even when its `match` finds several streams.

| Pool | Members |
|---|---|
| `apps` | The applications that play and have no channel of their own, one per slot. |
| `people` | The people of the voice chat without a `person` channel. |
| `auto` | The people and the applications together: people first, from the right. |
| `devices` | The outputs and inputs that no channel has (a USB headset). |
| your own, `[pool.<id>]` | Channels of a list (the first present one on the first slot, the next on the next), or with `kind`, the applications that match or the listed people. |

When a pool has no member for a slot, the slot goes on to the candidate below it: `["people", "apps"]` is a person
for as long as there is one, else an application.

## The same word, different things

A few words appear in several places with different meanings. The configuration keeps them apart; so should you.

| Word | Where it means what |
|---|---|
| `apps` | A channel type (a group of applications on one strip), the pool of applications on free slots, `[pool.apps]` (its settings), and the source `apps` of a state (an application plays). |
| `auto` | The pool of people and applications; what a slot without an entry shows; the override `auto` of a state or mode (the rules decide); the mode `auto` in Home Assistant (the same). |
| `device` | The X-Touch itself (`[device]`, the extender), and a sound device of an `output` or `input` channel (`device = "..."`). |
| `select` | The Select button, the option `select` of a device channel (whether the button makes it the default), and the Home Assistant entity type `select`. |
| `controls` | The section `[controls]` (actions of a slot's buttons, fader or encoder), and in general what a strip controls. |
| voice chat | The people of the voice chat (`[voip]`, the pool `people`, `person` channels), the state source `voice_chat`, and the preset `@voip` (the applications of voice chats). |

## More words

- **Place:** the options of a candidate in its slot, written `{ show = "auto", color = "blue" }` instead of a plain
  name.
- **Preset:** a name for a group of well-known applications, written with an `@` (`@browsers`, `@voip`). They come
  with the daemon, you can't define your own. See [Presets](configuration/presets.md).
- **Choices:** the devices Select switches between on one `output` or `input` channel. A **profile** is a setting of
  a sound card (analog or digital output) that a choice may need.
- **Override:** a state forced `on` or `off` from Home Assistant, the GUI or a button, until its sources change.
- **Chord:** two Solo buttons held together (slots 1 and 8 by default): it cycles the modes. The settings are in
  `[switching]`, which the GUI calls "Modes and chord".
- **Banner:** the label of a new mode (and why a slot changed) shown on the displays for `switching.banner` seconds.
- **Hold:** how long an application or device keeps its slot after it stopped (`hold` of `[pool.apps]` and
  `[pool.devices]`). A state's `delay_on` and `delay_off` smooth when the state turns on and off, and `absent_after`
  keeps a channel present for a moment. They are different settings for different things.

## Where to go next

[Channels, states and slots](configuration/slots.md) has every option of the model above, and the channel types have a
page each: [Devices](configuration/channels/devices.md), [Applications](configuration/channels/applications.md),
[People](configuration/channels/people.md). In the [GUI](guides/gui.md) the same parts have the pages Channels,
States and Slots.
