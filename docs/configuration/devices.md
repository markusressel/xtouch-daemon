# Devices: `output` and `input` strips

A device strip controls an output (a sink) or an input (a source): one device, one of several, or whatever is the
default.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"output"` or `"input"`. |
| `device` | the default device | The node name (`xtouch-daemon list-devices`) or the description of the device, or a list of them; `*` is a wildcard. Without it, the strip follows whatever device is the default. |
| `label` | see [Labels](strips.md#labels) | The top line of the LCD. With `profiles`, the label of the active profile comes first. |
| `select` | `true` | Whether Select makes the device the default. Needs `device`. |
| `profiles` | none | Profiles of the device's sound card that Rec switches between, see [below](#profiles). |
| `encoder` | `"balance"` | `balance` or `volume`, see [Encoders](encoders.md). |

They also have the [options of every audio strip](strips.md#options-of-every-audio-strip): `color`, `meter`, `rec`,
`solo`, `min_volume`, `max_volume`.

```toml
[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[[strip]]
type = "input"          # the default input
label = "Mic"
color = "red"
```

## Elements

| Element | Function |
|---|---|
| Fader | Sets the volume, `min_volume` at the bottom to `max_volume` at the top. Follows changes made elsewhere. |
| Encoder | See [Encoders](encoders.md): by default the balance. |
| Mute | Toggles mute. The LED is on while the device is muted. |
| Rec | With `profiles`: switches the sound card to the next profile. The LED is on for every profile but the first. Without `profiles` the LED is an [indicator](indicators.md). |
| Solo | Its LED is an [indicator](indicators.md). |
| Select | With `device` and `select`: makes the device the default output/input, or switches to the next of several. The LED is on while it is the default. |
| LCD | Top: the label. Bottom: the volume, or `muted`. |
| Ring | What the encoder controls. |
| Meter | The level: what plays on an output, what an input records. |

A device that is not there (e.g. Bluetooth headphones that are switched off) shows `off` on a dark LCD. Its fader goes
down, and the fader and buttons do nothing until it is back.

## The default device

A strip without `device` looks up the default device in every state of the sound server. It follows a switch of the
default, including its meter. Its Select button does nothing.

## Naming a device

`xtouch-daemon list-devices` lists the node names and descriptions of the outputs and inputs; `*` marks the defaults.

Use the node name for a device that is both an output and an input under one description, e.g. Bluetooth headphones
with a microphone. A description matches only devices of the strip's direction, but a node name is unambiguous and
stays the same across restarts.

## Several devices

`device` takes a list, and `*` wildcards match several devices. Wildcards work on node names and descriptions, and
are case-sensitive.

```toml
[[strip]]
type = "output"
device = ["bluez_output.*"]   # whichever Bluetooth headphones are connected
color = "green"

[[strip]]
type = "output"
device = ["alsa_output.usb-Focusrite*", "alsa_output.pci-0000_11_00.4.analog-stereo"]
label = "Main"
color = "cyan"
```

With several devices, the strip shows one of those that are there: the default one, or else the one it showed last.
Select makes it the default. Pressed on the default one, it switches to the next one that is there and makes that the
default. Without `label`, the LCD shows which one it is.

## Profiles

A sound card has profiles that decide which devices it has, e.g. analog or digital (S/PDIF, IEC958) output. Each
profile has a device of its own, so name `device` with a wildcard that matches all of them. With `profiles`, Rec
switches the card to the next one:

```toml
[[strip]]
type = "output"
device = "alsa_output.pci-0000_11_00.4.*"   # the analog and the digital output of the card
profiles = [
  { label = "Phones", profile = "output:analog-stereo+input:analog-stereo" },
  { label = "Speaker", profile = "output:iec958-stereo+input:analog-stereo", max_volume = 200 },
]
```

| Option | Default | Meaning |
|---|---|---|
| `label` | required | The name of the strip on the LCD while the card is in this profile, e.g. what is connected to that output (7 characters). |
| `profile` | required | The name or the description of the profile. `xtouch-daemon list-devices` lists the profiles of each card; `*` marks the active one. |
| `min_volume` | the strip's | The volume of the fader at the bottom in this profile. |
| `max_volume` | the strip's | The volume of the fader at the top in this profile, e.g. 200 for weak speakers. |

- At least two profiles: one alone has nothing to switch to.
- The label changes on the press of Rec. In a profile that isn't in the list, the strip's `label` shows.
- The Rec LED is on for every profile but the first, so `rec` can't be set on a strip with profiles.
- If the old device was the default, the new one becomes the default.
- Each device has its own volume: the fader moves to the volume of the new one.
- A card in a profile that isn't in the list switches to the first one.
