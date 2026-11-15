# Strips

Each `[[strip]]` section configures one strip of the device, from the left. Up to eight. Strips that are not
configured are `auto` strips.

```toml
[[strip]]
type = "input"
label = "Mic"
color = "red"
```

`type` picks what the strip controls:

| `type` | Page |
|---|---|
| `output`, `input` | [Devices](devices.md) |
| `apps`, `auto` | [Applications](applications.md) |
| `homeassistant` | [Home Assistant](../home-assistant.md) |
| `empty` | [below](#empty-strips) |

## Options of every audio strip

These options apply to `output`, `input`, `apps` and `auto` strips. `homeassistant` strips have only `color` of them,
`empty` strips none.

| Option | Default | Meaning |
|---|---|---|
| `color` | `"white"` | The LCD backlight: `off`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`. |
| `meter` | `true` | Whether this strip's LED meter shows the level (if `behavior.meters` is on). |
| `rec` | `"recording"` | What the LED of the Rec button shows, see [LEDs](indicators.md). |
| `solo` | `"off"` | What the LED of the Solo button shows, see [LEDs](indicators.md). |
| `min_volume` | `0` | The volume of the fader at the bottom, 0..200 percent. |
| `max_volume` | `behavior.max_volume` | The volume of the fader at the top, 0..200 percent. |
| `encoder` | depends on the type | What the encoder does, see [Encoders](encoders.md). |
| `fader` | `"volume"` | `"homeassistant"` hands the fader to Home Assistant, see [Encoders](encoders.md#fader-homeassistant). |
| `id` | `"strip_<position>"` | With `fader` or `encoder` in Home Assistant: part of the entity IDs, see [Home Assistant](../home-assistant.md#audio-strips-with-home-assistant-controls). |

Device and application strips also have a `label`, see their pages.

## Labels

A label is the top line of the LCD: at most 7 characters of ASCII, which is what fits. The bottom line shows the
volume, or the state of the strip (`muted`, `idle`, `off`).

Where the label comes from:

| Strip | Label |
|---|---|
| `output`, `input` | The label of the active [profile](devices.md#profiles), else `label`. Without both: the start of the device's description with `device`, `"Output"`/`"Input"` without it. |
| `apps` | `label` (required). |
| `auto` | The alias of the application from [`[aliases]`](behavior.md#aliases), or its name. |
| `homeassistant` | What Home Assistant sets, until then `label`. |

## Volume range

The fader covers `min_volume` at the bottom to `max_volume` at the top. The encoder stays in that range too. For
example, speakers that need amplification:

```toml
[[strip]]
type = "output"
device = "alsa_output.usb-Generic_USB_Audio-00.analog-stereo"
label = "Desk"
min_volume = 50
max_volume = 200
```

- Above 100 % the sound server amplifies the audio in software.
- `min_volume` must be below `max_volume`. Without `max_volume` the top is `behavior.max_volume`.
- [Profiles](devices.md#profiles) of a device strip can have a range of their own.
- `homeassistant` strips have no range: Home Assistant decides what their fader means.

## Elements of a strip

| Element | What it does on an audio strip |
|---|---|
| Fader | Sets the volume. Follows changes made elsewhere. Only a touched fader changes the volume. |
| Encoder | What `encoder` says, see [Encoders](encoders.md). |
| Mute | Toggles mute. Its LED is on while muted. |
| Rec, Solo | Their LEDs are [indicators](indicators.md). The buttons do nothing, except Rec with [profiles](devices.md#profiles). |
| Select | On device strips: makes the device the default. Nothing on application strips. |
| LCD | Top: the label. Bottom: the volume, or `muted`, `idle`, `off`. The backlight in `color`, dark while the strip has nothing to control. |
| Ring | What the encoder controls. |
| Meter | The level of what the strip controls. |

A strip with nothing to control (a device that is gone, an application that ended) goes dark, and its fader glides
slowly to the bottom. When it is back, the fader goes up to its volume again.

## Empty strips

```toml
[[strip]]
type = "empty"
```

A dark strip that does nothing. Its fader stays at the bottom. It has no options besides `type`.
