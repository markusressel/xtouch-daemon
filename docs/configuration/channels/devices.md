# Devices: `output` and `input` channels

A device channel controls an output (a sink) or an input (a source): one device, one of several, or whatever is the
default. With [`choices`](#choices), Select switches between several devices, each maybe in a profile of its sound
card.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"output"` or `"input"`. |
| `device` | the default device | The node name (`xtouch-daemon list-devices`) or the description of the device, or a list of them; `*` is a wildcard. Without it, the strip follows whatever device is the default. |
| `label` | see [Labels](index.md#labels) | The top line of the LCD. With `profiles`, the label of the active profile comes first. |
| `select`, `rec`, `solo` | see [Buttons](../strip/leds.md#buttons) | What the buttons do and what their LEDs show. By default Select makes the device the default (with `device` or `choices`) and Rec switches `profiles`. |
| `choices` | none | The devices Select switches between, each maybe in a profile of its card, see [below](#choices). Instead of `device` and `profiles`. |
| `profiles` | none | Profiles of the device's sound card that Rec switches between, see [below](#profiles). |
| `encoder` | `"balance"` | `balance` or `volume`, see [Encoders](../strip/encoders.md). |

They also have the [options of every audio channel](index.md#options-of-every-audio-channel): `color`, `meter`, `rec`,
`solo`, `min_volume`, `max_volume`.

```toml
[channel.out]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[channel.mic]
type = "input"          # the default input
label = "Mic"
color = "red"
```

## Elements

| Element | Function |
|---|---|
| Fader | Sets the volume, `min_volume` at the bottom to `max_volume` at the top. Follows changes made elsewhere. |
| Encoder | See [Encoders](../strip/encoders.md): by default the balance. |
| Mute | Toggles mute. The LED is on while the device is muted. |
| Rec | With `profiles`: switches the sound card to the next profile. The LED is on for every profile but the first. Without `profiles` (also with `choices`) the LED is an [indicator](../strip/leds.md#indicators). |
| Solo | Its LED is an [indicator](../strip/leds.md#indicators). |
| Select | With `device`: makes the device the default output/input, or switches to the next of several. With `choices`: the next choice. The LED is on while it is the default. |

That is what the buttons do by default; [Buttons](../strip/leds.md#buttons) gives them other actions, and a hold:
e.g. `next` shows the next device without making it the default, `talk` unmutes an input while held.
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
[channel.phones]
type = "output"
device = ["bluez_output.*"]   # whichever Bluetooth headphones are connected
color = "green"

[channel.main]
type = "output"
device = ["alsa_output.usb-Focusrite*", "alsa_output.pci-0000_11_00.4.analog-stereo"]
label = "Main"
color = "cyan"
```

With several devices, the strip shows one of those that are there: the default one, or else the one it showed last.
Select makes it the default. Pressed on the default one, it switches to the next one that is there and makes that the
default. Without `label`, the LCD shows which one it is.

## Devices without a channel

The built-in pool `devices` holds the outputs and inputs that no `output` or `input` channel has, e.g. a USB headset
or Bluetooth speakers. A channel has the devices its `device` matches; a channel without `device` has the default
device of its direction. A slot that names `devices` shows the next of them as an `output` or `input` strip of that
one device: its volume on the fader, Mute, Select makes it the default. `auto` doesn't take devices.

```toml
[slots]
8 = ["devices", "apps"]   # a headset that was plugged in, else an application

[pool.devices]
from = "left"                 # the side the devices fill from (default)
exclude = ["*HDMI*", "alsa_output.pci-*"]   # never a member: node names or descriptions, `*` wildcards
hold = 5                      # seconds a device keeps its slot after it went away (default 5)
color = "cyan"                # the look of the strips of devices, as on an output channel
encoder = "volume"            # balance (default) or volume
```

`[pool.devices]` and a place of `devices` (`{ show = "devices", select = false }`) take the look options of every
audio channel, `encoder` (`balance` or `volume`), `min_volume`, `max_volume`, and `select = false` (Select does not make
the device the default).

A device that goes away stays on its slot for `hold` seconds (its strip shows `off`), so a short drop of a Bluetooth
link doesn't move the strips. `present(devices)` holds while a device of the pool is there.

## Choices

`choices` is one strip for several devices that are used one at a time, e.g. headphones on the analog output of a
sound card, speakers on its digital output, and Bluetooth headphones. Select goes to the next one, and switches the
card to the profile it needs first:

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
label = "Speaker"
device = "alsa_output.pci-0000_11_00.4.iec958-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:iec958-stereo+input:analog-stereo"
max_volume = 200

[[channel.out.choices]]
label = "Buds"
device = "bluez_output.*"
```

A choice on one line is a TOML inline table: `{ label = "Buds", device = "bluez_output.*" }` in
`choices = [...]`. An inline table can't span several lines, so the `[[channel.out.choices]]` tables above are easier
to read for long ones.

| Option | Default | Meaning |
|---|---|---|
| `device` | required | The node name or description of the device; `*` and `?` are wildcards (the first device that matches). |
| `label` | the start of the description | The top line of the LCD while this choice is active (7 characters). |
| `card` | none | The sound card whose `profile` the choice needs: its name or description, wildcards allowed. Only with `profile`. |
| `profile` | none | The name or description of the profile of `card` the device is in. Only with `card`. Without both the device is used as it is. |
| `min_volume` | the strip's | The volume of the fader at the bottom while this choice is active. |
| `max_volume` | the strip's | The volume of the fader at the top while this choice is active, e.g. 200 for weak speakers. |

`xtouch-daemon list-devices` lists the devices, then each sound card (its name, its description and its devices)
with its profiles (name and description; `*` marks the active one): that is where `card` and `profile` come from.
A device of another profile appears only once the card is in that profile, so write its name as the sound server
will call it (usually `alsa_output.<card>.<profile output>`, e.g. `iec958-stereo`), or use a wildcard.

- **Which one shows:** the choice whose device is the default. If none of them is, the one shown last (if it is still
  there), or else the first one there is. A choice is there when its device is, or when its card is there and has
  its profile.
- **Select** goes to the next choice that is there, after the one shown, and around. A choice in another profile
  switches the card first, then its device becomes the default. The label shows the choice at once; if a switch
  fails, the strip goes back. Pressed again while a switch is on its way, Select goes on from where that one goes,
  so a few quick presses step through the choices. Pressed on a choice that is shown but isn't the default, it
  makes that one the default first.
- **The LED** of Select is on while the device of the choice is the default. Rec keeps its
  [indicator](../strip/leds.md#indicators) (`rec`).
- **Without making it the default:** `select = { hold = "next" }` (or `press = "next"`) shows the next choice whose
  device is there; the default stays, until it changes. See [Buttons](../strip/leds.md#buttons).
- **Elsewhere:** a default chosen elsewhere (pavucontrol, headphones that connect and become the default) shows on
  the strip if it is one of the choices.
- Two choices on the same card in the same profile only switch the default.
- Fader, Mute and the encoder act on the device of the choice shown; its range is the choice's `min_volume` and
  `max_volume`, else the strip's.
- While none of the choices is there, the strip is dark and shows `off`; `"out if present"` in a slot shows
  something else then.
- With [`[mqtt]`](../../guides/home-assistant.md#choices), Home Assistant has a select for the choice.

At least two choices, and not together with `device` or `profiles`; a button must switch between them (`default` or
`next`), so `select = false` needs another button that does.
In the GUI, `device` and `choices` are one list, Device: it writes `device` while its entries are devices alone, and
`choices` once one has a label, a profile or a volume range.
`profiles` (below) still works, but `choices` does the same with one button; the GUI shows `profiles` only for a channel
that has it.

## Profiles

A sound card has profiles that decide which devices it has, e.g. analog or digital (S/PDIF, IEC958) output. Each
profile has a device of its own, so name `device` with a wildcard that matches all of them. With `profiles`, Rec
switches the card to the next one (see [Choices](#choices) for the same with Select):

```toml
[channel.out]
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

Next: [Applications](applications.md), [People](people.md), or the [slots](../slots.md) that show them.
