# Devices: `output` and `input` channels

An `output` or `input` channel controls one sound device at a time: an output such as your speakers or an input such as your
microphone. It can follow a fixed one, pick one of several, or follow whichever is the default. With
[`choices`](#choices), Select switches between several, each optionally in a profile of its sound card.

| Option | Default | Meaning |
|---|---|---|
| `type` | required | `"output"` or `"input"`. |
| `device` | the default output or input | The node name or the description of the sound device (see [`xtouch-daemon list-devices`](../../reference/commands.md)), or a list of them. `*` and `?` are wildcards (any text, one character). |
| `label` | see [Labels](index.md#labels) | The top line of the LCD. The label of the active profile or choice wins. |
| `select`, `rec`, `solo` | see [Buttons](../strip/leds.md#buttons) | What the buttons do and what their LEDs show. By default Select makes the sound device the default (with `device` or `choices`) and Rec switches `profiles`. |
| `choices` | none | The sound devices Select switches between, see [below](#choices). Instead of `device` and `profiles`. |
| `profiles` | none | Profiles of the sound card that Rec switches between, see [below](#profiles). |
| `encoder` | `"balance"` | `balance` or `volume`, see [Encoders](../strip/encoders.md). |

They also have the [options of every audio channel](index.md#options-of-every-audio-channel).

```toml
[channel.out]
type = "output"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
label = "Speaker"
color = "cyan"

[channel.mic]
type = "input"          # no `device`: whichever microphone is the default
label = "Mic"
color = "red"
```

## Elements

The elements work as on [every audio strip](index.md#elements-of-a-strip). Here is what differs:

- **Encoder:** the balance by default ([Encoders](../strip/encoders.md)).
- **Select:** with `device`, makes the sound device the default, or switches to the next of several. With
  `choices`, goes to the next choice. The LED is on while it is the default.
- **Rec:** with `profiles`, switches the sound card to the next profile; the LED is on for every profile but the
  first. Else its LED is an [indicator](../strip/leds.md#indicators). Solo too.

[Buttons](../strip/leds.md#buttons) gives the buttons other actions, e.g. `next` or `talk`.

If the output is not there (your Bluetooth headphones are switched off), the strip shows `off` on a dark LCD, its
fader goes down, and the fader and buttons do nothing until it is back.

## The default sound device { #the-default-device }

A strip without `device` follows the default output (or input) of the sound server when it changes (you plug in a
headset). Select does nothing on it: there is no sound device of its own to make the default.

## Naming a sound device { #naming-a-device }

`xtouch-daemon list-devices` lists the node names and descriptions; `*` marks the defaults.

An `output` channel matches only outputs, an `input` channel only inputs, so a description that both share
(Bluetooth headphones with a microphone) still finds the right one. A node name stays the same across restarts; a
description can be the same for several sound devices. Use the node name to be sure.

## Several sound devices { #several-devices }

`device` takes a list, and wildcards (case-sensitive) match several sound devices.

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

With several matches, the strip shows the default one that is there, else the one it showed last. Select makes it
the default; pressed on the default one, it switches to the next and makes that the default. Without `label`, the
LCD shows which one it is.

## Devices without a channel

The built-in [pool](../slots.md#slots) `devices` holds the outputs and inputs that no channel owns, for
example a USB headset or Bluetooth speakers. A channel owns a sound device when its `device` matches it, or when it
has no `device` and the sound device is the default. So with a bare `[channel.out]`, the default output is never in
the pool.

A slot that names `devices` shows the next output or input of the pool as a strip of that sound device: its volume
on the fader, Mute, and Select makes it the default. `auto` doesn't take sound devices.

```toml
[slots]
8 = ["devices", "apps"]   # a headset that was plugged in, else an application

[pool.devices]
from = "left"                 # the side the sound devices fill from (default)
exclude = ["*HDMI*", "alsa_output.pci-*"]   # never a member: node names or descriptions, `*` wildcards
hold = 5                      # seconds a sound device keeps its slot after it went away (default 5)
color = "cyan"                # the look of these strips, as on an `output` channel
encoder = "volume"            # balance (default) or volume
```

`[pool.devices]` and a place of `devices` (`{ show = "devices", select = false }`) take the look options, `encoder`,
`min_volume`, `max_volume`, and `select = false` (Select does not make the sound device the default).

A sound device that goes away stays on its slot for `hold` seconds (its strip shows `off`), so a short drop of a
Bluetooth link doesn't move the strips. `devices if present` holds while the pool has a sound device, see
[Conditions](../slots.md#conditions).

## Choices

`choices` is one strip for several outputs that you use one at a time, e.g. headphones on the analog output of a
sound card, speakers on its digital output, and Bluetooth headphones. Select goes to the next one, switching the
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

A choice also works as an inline table in `choices = [...]`: `{ label = "Buds", device = "bluez_output.*" }`.

| Option | Default | Meaning |
|---|---|---|
| `device` | required | The node name or description, wildcards as above (the first match). |
| `label` | the start of the description | The top line while this choice is active (7 characters). |
| `card` | none | The sound card whose `profile` the choice needs: its name or description, wildcards allowed. Only with `profile`. |
| `profile` | none | The name or description of the profile of `card` that the choice needs. Only with `card`. Without both, the strip uses the output as it is. |
| `min_volume` | the strip's | The volume of the fader at the bottom while this choice is active. |
| `max_volume` | the strip's | The volume of the fader at the top while this choice is active, e.g. 200 for weak speakers. |

`xtouch-daemon list-devices` lists each sound card with its profiles (name and description; `*` marks the active
one): that is where `card` and `profile` come from. An output of another profile appears only once the card is in
that profile, so write its name as the sound server will call it, or use a wildcard. The name is `alsa_output.` plus
the card name without `alsa_card.`, a dot, and the output part of the profile: for `alsa_card.pci-0000_11_00.4` and
`output:iec958-stereo+input:analog-stereo` it is `alsa_output.pci-0000_11_00.4.iec958-stereo`.

- **Which one shows:** the choice whose output is the default; else the one shown last, if it is still there; else
  the first one there. A choice is there when its output is, or when its card is there and has its profile.
- **Select** goes to the next choice that is there, and around. A choice in another profile switches the card
  first, then its output becomes the default. The label shows the choice at once; if a switch fails, the strip goes
  back. Quick presses step through the choices. Pressed on a choice that is shown but isn't the default, it makes
  that one the default first.
- **The LED** of Select is on while the output of the choice is the default. Rec keeps its
  [indicator](../strip/leds.md#indicators).
- **Without making it the default:** give Select the action `next`, e.g. `select = { hold = "next" }` (`press` does
  it at a press). See [Buttons](../strip/leds.md#buttons).
- A default chosen elsewhere (pavucontrol, headphones that connect) shows on the strip if it is one of the choices.
- Two choices on the same card and profile only switch the default.
- Fader, Mute and the encoder act on the output of the choice shown, in the choice's range, else the strip's.
- While no choice is there, the strip is dark and shows `off`; `"out if present"` in a slot shows something else.
- With [`[mqtt]`](../../guides/home-assistant.md#choices), Home Assistant has a select for the choice.

Rules for `choices`:

- Write at least two choices.
- Do not combine `choices` with `device` or `profiles`.
- One button must switch between the choices (`default` makes the shown output the default, `next` only shows the
  next one). If you turn Select off with `select = false`, another button must do it.

`profiles` (below) still works, but `choices` does the same with one button. In the GUI, `device` and `choices` are
one list, "Device" (the sound device, not the X-Touch): it writes `choices` once an entry has a label, a profile or
a volume range. The GUI shows `profiles` only for a channel that has it.

## Profiles

A sound card has profiles that decide which outputs and inputs it has, e.g. analog or digital (S/PDIF, IEC958)
output. Each profile has an output of its own, so name `device` with a wildcard that matches all of them. Rec
switches the card to the next profile:

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
| `label` | required | The top line while the card is in this profile (7 characters). |
| `profile` | required | The name or description of the profile, from `xtouch-daemon list-devices`. |
| `min_volume` | the strip's | The volume of the fader at the bottom in this profile. |
| `max_volume` | the strip's | The volume of the fader at the top in this profile, e.g. 200 for weak speakers. |

- Write at least two profiles.
- While the card is in a profile that isn't in the list, the strip's `label` shows, and Rec switches to the first
  profile of the list.
- Profiles take Rec, so you can't set `rec` on such a strip.
- If the old output was the default, the new one becomes the default.
- Each output has its own volume: the fader moves to the volume of the new one.

Next: [Applications](applications.md), [People](people.md), or the [slots](../slots.md) that show them.
