# Devices: `output` and `input` channels

A device channel controls an output (a sink) or an input (a source): one device, one of several, or whatever is the
default. With [`choices`](#choices), Select switches between several devices, each optionally in a profile of its sound
card.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"output"` or `"input"`. |
| `device` | the default device | The node name or the description of the device (both are in the output of [`xtouch-daemon list-devices`](../../reference/commands.md)), or a list of them. `*` and `?` are wildcards (`*` matches any text, `?` one character). Without `device`, the strip follows whichever device is the default at the moment. |
| `label` | see [Labels](index.md#labels) | The top line of the LCD. With `profiles` or `choices`, the label of the active profile or choice wins over this `label`. |
| `select`, `rec`, `solo` | see [Buttons](../strip/leds.md#buttons) | What the buttons do and what their LEDs show. By default Select makes the device the default (with `device` or `choices`) and Rec switches `profiles`. |
| `choices` | none | The devices Select switches between, each optionally in a profile of its card, see [below](#choices). Instead of `device` and `profiles`. |
| `profiles` | none | Profiles of the device's sound card that Rec switches between, see [below](#profiles). |
| `encoder` | `"balance"` | `balance` or `volume`, see [Encoders](../strip/encoders.md). |

They also have the [options of every audio channel](index.md#options-of-every-audio-channel): `color`, `meter`, `rec`,
`solo`, `min_volume`, `max_volume`. `rec`, `solo` and `select` work as [Buttons](../strip/leds.md#buttons) describes.

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

| LCD | Top: the label. Bottom: the volume, or `muted`. |
| Ring | The LEDs around the encoder show the value the encoder sets. |
| Meter | The level: what plays on an output, what an input records. |

That is what the buttons do by default. [Buttons](../strip/leds.md#buttons) gives them other actions, and a second
action for a hold (pressing and holding the button). For example `next` shows the next device without making it the
default, and `talk` unmutes an input while you hold the button.

A device that is not there (e.g. Bluetooth headphones that are switched off) shows `off` on a dark LCD. Its fader goes
down, and the fader and buttons do nothing until it is back.

## The default device

A strip without `device` always controls whichever device the sound server has set as the default. When the default
changes (for example you plug in a headset), the strip follows it, including its meter. Select does nothing on such a
strip, because the strip has no device of its own to make the default.

## Naming a device

`xtouch-daemon list-devices` lists the node names and descriptions of the outputs and inputs; `*` marks the defaults.

A strip only looks at devices of its own direction: an `output` channel matches outputs, an `input` channel
inputs. So a description that two devices share (Bluetooth headphones with a microphone have one description for both)
still finds the right one. A node name names one device and stays the same across restarts, while a description can be the same for
several devices. Use the node name when you want one device for sure.

## Several devices

`device` takes a list, and `*` wildcards match several devices. Wildcards (`*` and `?`) work on node names and
descriptions, and are case-sensitive.

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

The built-in pool `devices` holds the outputs and inputs that no `output` or `input` channel owns, for example a USB
headset or Bluetooth speakers. A channel owns a device in two cases:

- The `device` of the channel matches it.
- The channel has no `device` and the device is the default of its direction. So with a bare `[channel.out]` of type
  `output`, the current default output is never in the pool.

A slot that names `devices` shows the next device of the pool as an `output` or `input` strip of that one device: its
volume on the fader, Mute, and Select makes it the default. `auto` doesn't take devices.

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
link doesn't move the strips. In a condition, `devices if present` and `present(devices)` hold while a device of the pool is there (see
[Conditions](../slots.md#conditions)).

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
| `device` | required | The node name or description of the device; `*` and `?` are wildcards, as above (the first device that matches). |
| `label` | the start of the description | The top line of the LCD while this choice is active (7 characters). |
| `card` | none | The sound card whose `profile` the choice needs: its name or description, wildcards allowed. Only with `profile`. |
| `profile` | none | The name or description of the profile of `card` the device is in. Only with `card`. Without both the device is used as it is. |
| `min_volume` | the strip's | The volume of the fader at the bottom while this choice is active. |
| `max_volume` | the strip's | The volume of the fader at the top while this choice is active, e.g. 200 for weak speakers. |

`xtouch-daemon list-devices` lists the devices, then each sound card (its name, its description and its devices)
with its profiles (name and description; `*` marks the active one): that is where `card` and `profile` come from.
A device of another profile appears only once the card is in that profile, so write its name as the sound server
will call it, or use a wildcard. The name is `alsa_output.` plus the card name without `alsa_card.`, a dot, and the output
part of the profile. Example: for the card `alsa_card.pci-0000_11_00.4` and the profile
`output:iec958-stereo+input:analog-stereo`, the device is `alsa_output.pci-0000_11_00.4.iec958-stereo`.

- **Which one shows:** the choice whose device is the default. If none of them is, the one shown last (if it is still
  there), or else the first one there is. A choice is there when its device is, or when its card is there and has
  its profile.
- **Select** goes to the next choice that is there, after the one shown, and around. A choice in another profile
  switches the card first, then its device becomes the default. The label shows the choice at once; if a switch
  fails, the strip goes back. A switch of the card takes a moment. If you press Select again during it, the second press moves on to the choice
  after the one being switched to. So a few quick presses step through the choices. Pressed on a choice that is shown but isn't the default, it
  makes that one the default first.
- **The LED** of Select is on while the device of the choice is the default. Rec keeps its
  [indicator](../strip/leds.md#indicators) (`rec`).
- **Without making it the default:** give Select the action `next`. It shows the next choice whose device is there, and
  the default stays as it is. Example: `select = { hold = "next" }` does this while you hold the button for half a
  second (`press = "next"` does it at a press). See [Buttons](../strip/leds.md#buttons). See [Buttons](../strip/leds.md#buttons).
- **Elsewhere:** a default chosen elsewhere (pavucontrol, headphones that connect and become the default) shows on
  the strip if it is one of the choices.
- Two choices on the same card in the same profile only switch the default.
- Fader, Mute and the encoder act on the device of the choice shown; its range is the choice's `min_volume` and
  `max_volume`, else the strip's.
- While none of the choices is there, the strip is dark and shows `off`; `"out if present"` in a slot shows
  something else then.
- With [`[mqtt]`](../../guides/home-assistant.md#choices), Home Assistant has a select for the choice.

Rules for `choices`:

- Write at least two choices.
- Do not combine `choices` with `device` or `profiles`.
- One button must switch between the choices (`default` or `next`, see [Buttons](../strip/leds.md#buttons)). If you
  turn Select off with `select = false`, another button must do it.

`profiles` (below) still works, but `choices` does the same with one button. In the GUI, `device` and `choices` are
one list, Device: it writes `device` while its entries are devices alone, and `choices` once one has a label, a
profile or a volume range. The GUI shows `profiles` only for a channel that has it.

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
- The label changes when you press Rec. While the card is in a profile that isn't in the list, the strip's `label` shows.
- Rec is taken by the profiles (its LED is on for every profile but the first), so you can't set `rec` on a strip with
  profiles.
- If the old device was the default, the new one becomes the default.
- Each device has its own volume: the fader moves to the volume of the new one.
- When you press Rec while the card is in a profile that isn't in the list, it switches to the first profile of the list.

Next: [Applications](applications.md), [People](people.md), or the [slots](../slots.md) that show them.
