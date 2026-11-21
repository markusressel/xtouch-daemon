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
1 = ["buds if present", "auto"]   # the buds while they are connected, else the next application or person
2 = ["game if gaming", "auto"]    # the game while the mode gaming is on, else the next application or person
```

Strips 3 to 8 have no entry, so each shows `auto`: the applications that play, or the people of the voice chat (see
[Pools](#pools)). (`@steam-games` is a [preset](#more-words), a name for a group of
applications that comes with the daemon.) Everything else in this documentation refines one of these
parts.

## Strips and slots

![One strip of the device, from the top: the encoder with its ring, the LCD, the meter beside Rec, Solo, Mute and Select, and the fader](images/controls/strip.png){ .xt-part width="88" }

The device has 8 **strips**. A strip is hardware. Each has, from the top:

<div class="grid cards" markdown>

-   ![Encoder](images/controls/encoder.png){ .xt-icon }
    **Encoder**

    ---

    Turns and pushes, with a ring of LEDs. See [Encoders](configuration/strip/encoders.md).

-   ![LCD](images/controls/lcd.png){ .xt-icon }
    **Display (LCD)**

    ---

    Two lines of 7 characters, with a backlight in the strip's color.

-   ![Buttons](images/controls/buttons.png){ .xt-icon }
    **Meter and buttons**

    ---

    The meter, and Rec, Solo, Mute and Select with their LEDs. See [Buttons and LEDs](configuration/strip/leds.md).

-   ![Fader](images/controls/fader.png){ .xt-icon }
    **Fader**

    ---

    A motor fader with a touch sensor, next to a dB scale.

</div>

A **slot** is the entry of the configuration for one strip, numbered 1 to 8 from the left. A slot decides what its
strip shows.

## Channels

A **channel** is a thing you define in the file and give one strip: a sound device, a group of applications, a person
of the voice chat, a strip for [Home Assistant](guides/home-assistant.md), or a value that your own programs read and
set. Its `type` says which:

| `type` | The strip controls |
|---|---|
| `output`, `input` | One sound device, one of several (`choices`), or the default one. |
| `apps` | All playback streams of a group of applications at once: one fader sets all of them. |
| `person` | One person of the voice chat. |
| `homeassistant` | Nothing by itself: its fader, encoder, display and buttons are entities in Home Assistant. |
| `custom` | Something other than audio, e.g. the brightness of a screen: you connect its fader, encoder, display and buttons to commands of your own. See [Custom channels](configuration/channels/custom.md). |

These are all the types. `auto` and `-` are not channel types: `auto` is a pool (see [Pools](#pools)) and `-` is a dark
strip. A channel has an id (`buds`, `game`) that names it in slots, conditions and Home Assistant. It takes a strip only
when a slot names it.

Applications are controlled on the playback side only. An `apps` channel sets the volume of what an application
plays. What an application records is only observed: it lights the Rec LED and can turn on a state (see [States and modes](#states-and-modes)), but
no fader or Mute acts on it.

## Slots

A slot is a list of **candidates**, top first. It shows the first candidate whose condition holds:

```toml
[slots]
3 = ["game if gaming", "auto"]    # the game in the mode gaming, else the next application or person
4 = "mic"                         # a single candidate: always the microphone
5 = ["game if gaming", "-"]       # the game in the mode gaming, else a dark strip
```

A candidate is a channel or pool name, optionally followed by `if` and a **condition**; `-` is nothing (the strip
goes dark). A slot without an entry is `auto`. Only the slots whose candidate changes move; the others stay as they
are, and a strip you are touching keeps what it shows until you let go.

## States and modes

A **state** is on or off. You define it in a `[state.<name>]` section and list its sources, such as `apps`,
`recording`, `voice_chat`, `processes`, `devices` or `homeassistant`. It is on while any of its sources is: an application
plays or records, you are in the voice chat, a process runs, a device is there, or Home Assistant says so. Slots ask about states in their conditions
(`game if gaming`).

A **mode** is a state with `mode = true`. States are independent: `gaming` and `call` can be on together. Modes are
not: only one mode is on at a time, so a mode names the situation you are in now. In the example above, `gaming` is
a mode.

- When the sources of several modes are on, the one with the highest `priority` wins. `priority` is a number; it is 0
  if you give none.
- When no mode has a source on, the mode is `default`. You don't define it.
- A new mode shows its name across all displays for a moment (the banner).
- You can also pick a mode by hand: with the chord (see [More words](#more-words)), `xtouch-daemon mode`, a button or
  Home Assistant.

A condition such as `game if gaming` reads the same for a state and for a mode.

## Conditions

A condition is the text after `if`: names of states and modes joined with `and`, `or`, `not` and parentheses, plus
`present`. A channel is **present** while it has something to control: an application of an `apps` channel plays, its
device is there, the person is in the voice chat. `"buds if present"` shows the buds only while they are connected.

## Pools

A **pool** supplies members that you don't list one by one. Each slot that names the pool gets one member, in the order of
the slots, so one pool can fill several strips (`apps` and `devices` start at the left, at slot 1; `people` at the right, at slot 8. The option `from` of a pool
changes that): the next application that plays, the next person in the voice chat. A channel is the
opposite: you define it, and it takes exactly one strip, even when its `match` finds several streams.

| Pool | Members |
|---|---|
| `apps` | The applications that play, one per slot. An application whose channel has a slot of its own appears there instead; a channel that no slot names is one member, with all its streams, unless it has `in_pool = false`. |
| `people` | The people of the voice chat. For a `person` channel, the same rule as for `apps`. |
| `auto` | The people and the applications together. The people fill the slots from the right (slot 8 first), the applications from the left (slot 1 first). |
| `devices` | The outputs and inputs that no channel has (a USB headset). |
| your own, `[pool.<id>]` | A list of channels you name: the first one that is present goes to the first slot that names the pool, the next one to the next slot. With `kind = "apps"`, the applications that match a `match` list. With `kind = "people"`, the people on a `people` list. See [Channels, states and slots](configuration/slots.md#pools-of-channels). |

When a pool has no member for a slot, the slot goes on to the candidate below it: `["people", "apps"]` is a person
for as long as there is one, else an application.

## The same word, different things

A few words appear in several places with different meanings. The configuration keeps them apart; so should you.

| Word | Where it means what |
|---|---|
| `apps` | A channel type (a group of applications on one strip), the pool of applications on free slots, `[pool.apps]` (its settings), and the source `apps` of a state (an application plays). |
| `auto` | The pool of people and applications; what a slot without an entry shows; the value `auto` of an override or of the mode pick in Home Assistant (nothing set by hand: the sources decide). |
| `device` | The X-Touch itself (`[device]`, the extender), and a sound device of an `output` or `input` channel (`device = "..."`). |
| `select` | The Select button, the option `select` of a device channel (`select = true`: pressing the button makes that device the system default), and the Home Assistant entity type `select`. |
| `controls` | The section `[controls]` (actions of a slot's buttons, fader or encoder), and in general what a strip controls. |
| voice chat | The people of the voice chat (`[voip]`, the pool `people`, `person` channels), the state source `voice_chat`, and the preset `@voip` (the applications of voice chats). |

## More words

- **Place:** the options of a candidate in its slot. You write a table instead of a plain name, e.g.
  `4 = [{ show = "auto", color = "blue" }]` shows `auto` on slot 4 with a blue backlight.
- **Preset:** a name for a group of well-known applications, written with an `@` (`@browsers`, `@voip`). They come
  with the daemon, you can't define your own. See [Presets](configuration/presets.md).
- **Choices:** the devices Select switches between on one `output` or `input` channel. A **profile** is a setting of
  a sound card (analog or digital output) that a choice may need: a choice can say "this device, with the card in
  the digital profile". See [Devices](configuration/channels/devices.md#choices).
- **Override:** you set a state `on` or `off` by hand (in Home Assistant, in the GUI or with a button), whatever its
  sources say. It lasts until the sources change (with `persist = true`, until you set it back). The third value,
  `auto`, means no override: the sources decide.
- **Chord:** two Solo buttons held together (slots 1 and 8 by default): it cycles the modes. The settings are in
  `[switching]`, which the GUI calls "Modes and chord".
- **Banner:** the label of a new mode (and why a slot changed) shown on the displays for `switching.banner` seconds.
- **Hold, `delay_off` and `absent_after`:** three waiting times in seconds, each for a different thing.
    - `hold` (`[pool.apps]` and `[pool.devices]`, 5 by default): how long an application or device that stopped keeps
      its slot, so a pause between two songs does not hand the strip to another application.
    - `delay_off` (a state, 3 by default, 10 for a mode): how long the state stays on after its sources went off.
      `delay_on` (0 by default) is the wait before it turns on.
    - `absent_after` (a channel, 3 by default): a channel that has nothing to control any more still counts as `present` for this long, so a short gap
      does not make its slot move.

## Where to go next

[Channels, states and slots](configuration/slots.md) has every option of the model above, and the channel types have a
page each: [Devices](configuration/channels/devices.md), [Applications](configuration/channels/applications.md),
[People](configuration/channels/people.md). In the [GUI](guides/gui.md) the same parts have the pages Channels,
States and Slots.
