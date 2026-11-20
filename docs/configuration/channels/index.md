# Channels

Each `[channel.<id>]` section is something a strip of the device can control; [slots](../slots.md#slots) say which
strip shows it when. The id names it in slots, conditions and the entities in Home Assistant: lower case letters,
digits and `_`.

```toml
[channel.mic]
type = "input"
label = "Mic"
color = "red"
```

`type` picks what the channel controls:

| `type` | Page |
|---|---|
| `output`, `input` | [Devices](devices.md) |
| `apps` | [Applications](applications.md) |
| `person` | [People and the voice chat](people.md) |
| `homeassistant` | [Home Assistant](../../guides/home-assistant.md) |
| `command` | [Commands](commands.md) |

The strips of `auto` (the next application that plays) and empty slots (`-`) are no channels: they are written in
the [slots](../slots.md#slots).

Options about slots rather than the strip: `tags` (names to group channels under), `in_pool = false` (an `apps` or
`person` channel without a slot stays out of `apps`, `people` and `auto`) and `absent_after` (seconds the channel stays present after it
had nothing to control, for `if present`).

## Options of every audio channel

These options apply to `output`, `input` and `apps` channels. The look among them (`color`, `lit_when_idle`, `meter`,
`meter_point`, `rec`, `solo`) also goes into the built-in pools (`[pool.apps]`, `[pool.auto]`, `[pool.devices]`) and
into a place in a slot, for the strips they show; a place of `apps`, `auto` or `devices` also takes `encoder`,
`min_volume` and `max_volume`. `homeassistant` channels have only `color` of them, `person` channels their own
([People](people.md#the-strips-of-people)).

| Option | Default | Meaning |
|---|---|---|
| `color` | `"white"` | The LCD backlight: `off` (no backlight), `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`. Dark while the strip has nothing to control, unless `lit_when_idle` is on. |
| `lit_when_idle` | `false` | Whether the LCD keeps its backlight while the strip has nothing to control: no application of an `apps` group plays, the device is not there, an `auto` strip has no application. The fader stays down all the same. |
| `meter` | `true` | Whether this strip's LED meter shows the level (if `behavior.meters` is on). |
| `meter_point` | `behavior.meter_point` | Where the meter takes the level: `"pre_fader"` before the volume and Mute of the strip, `"post_fader"` after them, see [Meters](#meters). |
| `rec` | `"recording"` | What the Rec button does and what its LED shows; an indicator alone (`recording`, `playing`, `default`, `muted` or `off`) sets the LED, see [Buttons and LEDs](../strip/leds.md). |
| `solo` | `"off"` | The same for Solo, see [Buttons and LEDs](../strip/leds.md). |
| `select` | what the type does | The same for Select, see [Buttons and LEDs](../strip/leds.md#buttons). |
| `min_volume` | `0` | The volume of the fader at the bottom, 0..200 percent. |
| `max_volume` | `behavior.max_volume` | The volume of the fader at the top, 0..200 percent. |
| `encoder` | depends on the type | What the encoder does, see [Encoders](../strip/encoders.md). |
| `fader` | `"volume"` | `"homeassistant"` hands the fader to Home Assistant, see [Encoders](../strip/encoders.md#fader-homeassistant). |

Device and application channels also have a `label`, see their pages. A candidate of a slot can change the look at
that place: `{ show = "mic", color = "blue" }` (see [Slots](../slots.md#slots)).

## Labels

A label is the top line of the LCD: at most 7 characters of ASCII, which is what fits. The bottom line shows the
volume, or the state of the strip (`muted`, `idle`, `off`).

Where the label comes from:

| Strip | Label |
|---|---|
| `output`, `input` | The label of the [choice](devices.md#choices) shown, or of the active [profile](devices.md#profiles), else `label`. Without one: the start of the device's description with `device`, `"Output"`/`"Input"` without it. |
| `apps` | `label` (required). |
| `apps`, `auto` in a slot | The alias of the application from [`[aliases]`](../behavior.md#aliases), or its name; an `apps` channel it hands out keeps its own `label`. |
| `devices` in a slot | The start of the device's description. |
| `person` | `label`, else the first name of `person`; people of `auto` show their name. |
| `homeassistant` | What Home Assistant sets, until then `label`. |

## Volume range

The fader covers `min_volume` at the bottom to `max_volume` at the top. The encoder stays in that range too. For
example, speakers that need amplification:

```toml
[channel.desk]
type = "output"
device = "alsa_output.usb-Generic_USB_Audio-00.analog-stereo"
label = "Desk"
min_volume = 50
max_volume = 200
```

- Above 100 % the sound server amplifies the audio in software.
- `min_volume` must be below `max_volume`. Without `max_volume` the top is `behavior.max_volume`.
- [Profiles](devices.md#profiles) and [choices](devices.md#choices) of a device can have a range of their own.
- `homeassistant` channels have no range: Home Assistant decides what their fader means.

### 100 % at the 0 dB mark

The scale next to the faders of the X-Touch Extender marks 0 dB at about 77 % of the travel. The faders of strips
that go above 100 % put 100 % there: from the bottom to the mark the fader covers `min_volume` to 100 %, from the
mark to the top 100 % to `max_volume`. Both parts are linear. `behavior.unity_at` (default `77`) moves the mark.

```toml
[behavior]
max_volume = 200   # the top 23 % of the travel amplify by up to 100 %
```

| Fader | A linear fader, 0..200 | The faders here, 0..200 |
|---|---|---|
| bottom | 0 % | 0 % |
| half way | 100 % | 65 % |
| 0 dB mark (77 %) | 154 % | 100 % |
| top | 200 % | 200 % |

With the default `max_volume = 130` the two parts have the same slope: the fader is linear from 0 % to 130 %, with
100 % at the mark. Strips whose range ends at 100 % (`max_volume = 100`) are not affected: their 100 % is at the
top. The GUI has the option under Settings, Behavior.

## Elements of a strip

| Element | What it does on an audio strip |
|---|---|
| Fader | Sets the volume. Follows changes made elsewhere. Only a touched fader changes the volume. |
| Encoder | What `encoder` says, see [Encoders](../strip/encoders.md). |
| Mute | Toggles mute. Its LED is on while muted. |
| Rec, Solo | Their LEDs are [indicators](../strip/leds.md#indicators). By default the buttons do nothing, except Rec with [profiles](devices.md#profiles). |
| Select | On device strips: makes the device the default, or with [`choices`](devices.md#choices) goes to the next one. On application strips with [`launch`](applications.md#launching-the-application): starts the application. Otherwise nothing on application strips. |
| | Every channel can give Rec, Solo and Select other actions, for a press and a hold: see [Buttons](../strip/leds.md#buttons). [`[controls]`](../slots.md#controls-and-the-chord) gives the buttons of a slot an action whatever it shows. |
| LCD | Top: the label. Bottom: the volume, or `muted`, `idle`, `off`. The backlight in `color`, dark while the strip has nothing to control. |
| Ring | What the encoder controls. |
| Meter | The level of what the strip controls, see [Meters](#meters). |

A strip with nothing to control (a device that is gone, an application that ended) goes dark, and its fader glides
slowly to the bottom. When it is back, the fader goes up to its volume again.

## Meters

The LED meter shows the peak level of what the strip controls, 10 times a second: from -60 dB (the lowest LED) up to
just below full scale (the seventh LED), 5 dB per level of the device (about two levels per LED, see
[Hardware](../../reference/hardware.md)). A peak at full scale lights the red LED at the top too, for half a second. The device
lets a meter fall by itself when no new level comes.

`meter_point` says where the level is taken, like the pre-fader and post-fader meters of a hardware mixer:

| `meter_point` | What the meter shows |
|---|---|
| `"pre_fader"` (default) | The level before the strip's volume and Mute: the meter keeps showing the audio while the fader is down, and the Mute LED says whether it goes on. |
| `"post_fader"` | The level after the volume and Mute: what you hear of an application, what goes out of the output, what applications get from the input. Dark while muted. |

What each strip type can show:

| Strip | `"pre_fader"` | `"post_fader"` |
|---|---|---|
| `output` | Before its volume and Mute, as PipeWire's monitor of the output has it. | Its monitor times its volume, nothing while muted. |
| `apps`, `auto` | The streams' audio divided by their volume, so the fader doesn't move the meter. **While muted the meter stays dark:** PipeWire applies the volume and Mute inside the stream, before anything else can listen, so the audio of a muted stream is gone. | The streams as they play. |
| `input` | The input divided by its volume. Dark while muted, as above. | The input as applications get it. |
| `person`, people | The voice before the participant's volume (the plugin's fader). Muted, Mumble doesn't fetch their voice: the meter lights while they talk, without a level. A plugin that tells no level before the volume shows the one after it. | The voice after their volume, dark while muted. |
| `homeassistant` | The meter entity, see [Home Assistant](../../guides/home-assistant.md). | |

The first that sets it wins: the `meter_point` of the place in a slot, the channel's, then `behavior.meter_point`.

```toml
[behavior]
meter_point = "pre_fader"     # every strip ...

[channel.out]
type = "output"
meter_point = "post_fader"    # ... but this one: what goes out of the speakers
```

A level divided by the volume is exact while the volume stays. While the fader moves, the audio lags behind its
volume by a few hundredths of a second: for 0.3 s after a change the meter divides by the loudest of the volumes
since, so a fader pulled down does not light the red LED; the meter shows too low for a moment instead.

## Empty slots

```toml
[slots]
4 = ["game if gaming", "-"]   # dark while not gaming
```

`-` in a slot is a dark strip that does nothing. Its fader stays at the bottom.
