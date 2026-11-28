# General settings

Three sections that you only need when the defaults do not fit: `[device]` is about the control surface itself,
`[behavior]` about the faders, encoders and meters of all strips, and `[aliases]` about the names that application
strips show. The [GUI](../guides/gui.md) has them on the page Settings.

## `[device]`

| Option | Default | Meaning |
|---|---|---|
| `name` | `"X-Touch-Ext"` | Part of the name of the sound card of the control surface, as `/proc/asound/cards` lists it. The daemon takes the first card whose id or description contains this text, with the same upper and lower case. In the card line `0 [XTouchExt      ]: USB-Audio - X-Touch-Ext`, the id is `XTouchExt` and the description is `USB-Audio - X-Touch-Ext`. The default fits the X-Touch Extender, so you rarely change it. |
| `virtual` | `false` | Drive the [virtual device](../getting-started/without-a-device.md) (the control surface drawn in the GUI) instead of the physical control surface (`xtouch-daemon run --virtual-device` does the same for one run). |
| `touch_required` | `true` | Whether a fader changes a value only while the control surface reports a touch. `false` makes every move count, see [below](#faders-without-a-touch-sensor). |
| `touchless_faders` | `[]` | Faders whose touch sensor does not work, numbered from 1 on the left, see [below](#faders-without-a-touch-sensor). |
| `startup` | `"sweep"` | How the strips light up after a connect, see [below](#startup-and-shutdown-sequences). |
| `shutdown` | `"sweep"` | How the strips go dark when the daemon stops, see [below](#startup-and-shutdown-sequences). |
| `startup_sweep_delay`, `shutdown_sweep_delay` | `80` | Milliseconds from one strip to the next in `sweep`, see [below](#the-pace-of-a-sequence). |
| `startup_curtain_delay`, `shutdown_curtain_delay` | `80` | Milliseconds from one pair of strips to the next in `curtain`. |
| `startup_show_delay`, `shutdown_show_delay` | `60` | Milliseconds from one strip to the next in `show`: the speed of the wave. |
| `startup_show_step`, `shutdown_show_step` | `30` | Milliseconds per step of the light of a strip in `show`, from 10 to 200. |
| `startup_show_fader`, `shutdown_show_fader` | `60` | The height, in percent, that the faders rise to in `show`. |

A reload takes every option of `[device]`: with another `name` or `virtual`, the daemon connects to the other control surface without a restart, and the strips show the same on it.

### Startup and shutdown sequences

After a connect the strips light up and their faders come up to their values; when the daemon stops, the strips go
dark and their faders go down. `startup` and `shutdown` choose how:

| Value | Startup | Shutdown |
|---|---|---|
| `instant` | All strips at once. | All strips at once. |
| `sweep` | One after the other from the left. | One after the other from the right. |
| `curtain` | From the middle outwards, pair by pair (4 and 5 first, 1 and 8 last). | From the outside in. |
| `show` | One wave of light runs across the strips from the left, in about 1 second at the default pace. As it passes a strip, the strip lights up fully and its fader rises. Then the light goes off, the fader falls to its value and the strip shows its content. | The same wave, from the right. Behind it, the strips are dark and their faders at the bottom. |

```toml
[device]
startup = "show"
shutdown = "curtain"
```

#### The pace of a sequence

Each sequence has options for its pace, separately for the startup and the shutdown. Their names start with the
direction and the sequence, e.g. `startup_sweep_delay` for the `sweep` at startup. An option of a sequence you don't
use changes nothing, and the GUI shows only the options of the chosen sequence.

- `sweep` and `curtain` have a delay: the milliseconds from one strip, or one pair of strips, to the next.
- `show` has a delay too, the milliseconds from one strip to the next. `step` is the milliseconds per step of the
  light of one strip: its ring lights one more LED and its meter one more level. The light takes 24 steps, 12 up and
  12 down, so with the default of 30 ms one strip takes about 0.7 seconds. `fader` is how high the faders rise, in
  percent; a fader whose value is higher stays at its value.
- `instant` has none.

```toml
[device]
startup = "sweep"
startup_sweep_delay = 40      # a faster sweep from the left
shutdown = "show"
shutdown_show_delay = 120     # a slow wave from the right
shutdown_show_fader = 100     # the faders go all the way up first
```

### Faders without a touch sensor

The daemon changes a value only while you touch the fader (see [Hardware](../reference/hardware.md#motor-faders)),
because the motor also moves the faders. With a broken touch sensor the daemon never sees a touch, so the motor moves
the fader back to its value shortly after every move you make. `touchless_faders` lets that fader work without the
sensor: a move counts as a touch, and half a second without a move counts as letting go. Count the faders from 1 on
the left. The GUI has toggles for it under Settings, Extender.

```toml
[device]
touchless_faders = [1]   # the touch sensor of fader 1 is broken
```

`touch_required = false` does the same for all faders, with the limits below. Use it also if a working sensor does
not notice your finger, e.g. when you push the fader from below.

```toml
[device]
touch_required = false   # every move of a fader counts
```

What it can't do:

- **Resting fingers:** a finger that rests on the fader without moving it counts as gone after half a second. If the
  value changed somewhere else in the meantime (e.g. in the volume control of the desktop), the fader moves out
  from under your finger.
- **The first 3 seconds after a connect:** the X-Touch Extender moves all its faders down by itself, so in these 3 seconds a
  fader counts a move only with a real touch.

## `[behavior]`

| Option | Default | Meaning |
|---|---|---|
| `max_volume` | `130` | The volume of a fader at the top, 100..200 percent. Above 100 % the audio is amplified in software. See [the volume scale](#the-volume-scale). Channels may have their own [range](channels/index.md#volume-range). |
| `unity_at` | `77` | Where on the fader 100 % is, 10..95 percent of the travel from the bottom. The scale printed next to the faders of the X-Touch Extender marks 0 dB at about 77. See [the volume scale](#the-volume-scale). |
| `encoder_step` | `1` | Percent per encoder step, 1..10. Used by the `volume` and `homeassistant` [encoders](strip/encoders.md), and as the default `step` of a [value of your own](channels/custom.md#a-value). |
| `reset_volume` | `100` | The volume a push on a `volume` encoder sets, 0..200. A value above `max_volume` is an error that `xtouch-daemon check-config` reports. If a channel has its own range, the push sets the nearest volume inside that range. |
| `meters` | `true` | Whether the LED meters show audio levels at all. The `meter` option of a channel turns off a single one. |
| `meter_point` | `"pre_fader"` | Where the meters take the level: `"pre_fader"` before the volume and Mute of each strip, so the meter shows what the application plays, even when you turned it down. `"post_fader"` after them, so the meter shows what you hear. A channel, or the entry of one slot in `[slots]`, may have its own, see [Meters](channels/index.md#meters). |

`hold` and `exclude` of the strips of applications are in [`[pool.apps]`](channels/applications.md#apps-and-auto).

```toml
[behavior]
max_volume = 150
encoder_step = 2
```

### The volume scale

`max_volume` and `unity_at` together say what volume each point of the fader has. The scale printed next to the faders
marks 0 dB (the volume the application sends, 100 %) at about 77 % of the travel, the default of `unity_at`. From the
bottom to that mark the fader goes linearly from 0 to 100 %, from the mark to the top from 100 % to `max_volume`.

- With the default `max_volume = 130` both parts have the same slope (100 / 130 is about 0.77): the fader is linear
  from 0 to 130 %.
- With a larger `max_volume` (up to 200) the part above the mark is steeper.
- With `max_volume = 100`, 100 % is at the top and `unity_at` is ignored.

Examples and a table are at [100 % at the 0 dB mark](channels/index.md#100-at-the-0-db-mark).

## `[aliases]`

The name that a strip shows for an application, in place of the name the sound server reports. It applies to strips
that take their application from the pools `apps` and `auto`, and to pools of your own with `kind = "apps"`
([Applications](channels/applications.md#apps-and-auto)). An `apps` channel shows its `label` instead. An alias has
at most 7 ASCII characters, to fit the LCD; `check-config` reports a longer one.

```toml
[aliases]
"WEBRTC VoiceEngine" = "Discord"
"Chromium" = "Browser"
```

The key is the application name the sound server reports, with the same upper and lower case. `xtouch-daemon list-apps`
and the GUI's suggestions show it.

Next: [Commands](../reference/commands.md), [Troubleshooting](../guides/troubleshooting.md).
