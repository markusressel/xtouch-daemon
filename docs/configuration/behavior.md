# Behavior, device and aliases

Three sections that you only need when the defaults do not fit: `[device]` is about the extender itself,
`[behavior]` about the faders, encoders and meters of all strips, and `[aliases]` about the names that application
strips show. Put them in the [configuration file](index.md) like any other section; the daemon applies a saved file
by itself. The [GUI](../guides/gui.md) has them on the page Settings.

A complete example that uses all three:

```toml
[device]
startup = "show"
shutdown = "curtain"
touchless_faders = [3]      # the touch sensor of fader 3 is broken

[behavior]
max_volume = 150
encoder_step = 2

[aliases]
"WEBRTC VoiceEngine" = "Discord"
```

## `[device]`

| Option | Default | Meaning |
|---|---|---|
| `name` | `"X-Touch-Ext"` | Part of the name of the extender's sound card, as `/proc/asound/cards` lists it. The daemon takes the first card whose id or description contains this text, with the same upper and lower case. In the card line `0 [XTouchExt      ]: USB-Audio - X-Touch-Ext`, the id is `XTouchExt` and the description is `USB-Audio - X-Touch-Ext`. The default fits a real X-Touch Extender, so you rarely change it. |
| `virtual` | `false` | Drive the [virtual device](../getting-started/without-a-device.md) instead of the real one (`xtouch-daemon run --virtual-device` does the same for one run). |
| `touch_required` | `true` | Whether a fader changes a value only while the device reports a touch. `false` makes every move count, see [below](#faders-without-a-touch-sensor). |
| `touchless_faders` | `[]` | Faders whose touch sensor does not work, numbered from 1 on the left, see [below](#faders-without-a-touch-sensor). |
| `startup` | `"sweep"` | How the strips light up after a connect, see [below](#startup-and-shutdown-sequences). |
| `shutdown` | `"sweep"` | How the strips go dark when the daemon stops, see [below](#startup-and-shutdown-sequences). |

When the daemon applies a saved file (a reload), it takes every option of `[device]`. With another `name` or `virtual` the daemon lets go of the device and connects to the
other one. The new device shows what the old one showed.

### Startup and shutdown sequences

After a connect the strips light up and their faders come up to their values; when the daemon stops, the strips go
dark and their faders go down. `startup` and `shutdown` choose how:

| Value | Startup | Shutdown |
|---|---|---|
| `instant` | All strips at once. | All strips at once. |
| `sweep` | One after the other from the left, 80 ms apart. | One after the other from the right. |
| `curtain` | From the middle outwards, pair by pair (4 and 5 first, 1 and 8 last). | From the outside in. |
| `show` | One wave of light runs across the strips from the left. Each strip does three things as the wave passes it. First, it turns white, its ring fills up from the left, its meter goes up, its buttons light up from the top (Rec first) and its fader rises. Then this light goes off in the same order and the fader falls to its value. Last, the strip shows its own content. The wave takes about 1.1 s after the connect. | The same wave, from the right. Behind it, the strips are dark and their faders at the bottom. |

```toml
[device]
startup = "show"
shutdown = "curtain"
```

### Faders without a touch sensor

The daemon changes a value only while you touch the fader (see [Hardware](../reference/hardware.md#motor-faders)),
because the motor also moves the faders. The symptom of a broken touch sensor: the daemon never sees a touch, so the
motor moves the fader back to its value shortly after every move you make. Until you repair the sensor, `touchless_faders` lets that fader work without it: a move counts as a touch,
and half a second without a move counts as letting go. Count the faders from 1 on the left. In the GUI these are the toggles of
`touchless_faders` under Settings, Extender.

```toml
[device]
touchless_faders = [1]   # the touch sensor of fader 1 is broken
```

`touch_required = false` does the same for all faders, and it has the limits listed below. Use it also if a working sensor does not notice some hands, e.g.
a fingertip that pushes the fader from below: with `touch_required = false`, such a push counts too.

```toml
[device]
touch_required = false   # every move of a fader counts
```

What it can't do:

- **Resting fingers:** the daemon treats a finger that rests on the fader without moving it as gone after half a
  second. The motor then moves the fader to its value, which is where your finger left it, so you notice nothing. If
  the value changed somewhere else in the meantime (e.g. in the volume control of the desktop), the fader moves out
  from under your finger.
- **The first 3 seconds after a connect:** when the device connects, it moves all its faders down by itself, and the
  daemon must not take that for your hand. So for a fader with `touchless_faders` (or with `touch_required = false`),
  a move in the first 3 seconds counts only with a real touch, like on the other faders. After that, a move counts
  as a touch again.

## `[behavior]`

| Option | Default | Meaning |
|---|---|---|
| `max_volume` | `130` | The volume of a fader at the top, 100..200 percent. Above 100 % the audio is amplified in software. See [the volume scale](#the-volume-scale). Channels may have their own [range](channels/index.md#volume-range). |
| `unity_at` | `77` | Where on the fader 100 % is, 10..95 percent of the travel from the bottom. The device marks 0 dB at about 77. See [the volume scale](#the-volume-scale). |
| `encoder_step` | `1` | Percent per encoder step, 1..10. Used by the `volume` [encoder](strip/encoders.md) and by the encoders of `homeassistant` channels. |
| `reset_volume` | `100` | The volume a push on a `volume` encoder sets, 0..200. A value above `max_volume` is an error that `xtouch-daemon check-config` reports. If a channel has its own range, the push sets the nearest volume inside that range. |
| `meters` | `true` | Whether the LED meters show audio levels at all. The `meter` option of a channel turns off a single one. |
| `meter_point` | `"pre_fader"` | Where the meters take the level: `"pre_fader"` before the volume and Mute of each strip, so the meter shows what the application plays, even when you turned it down. `"post_fader"` after them, so the meter shows what you hear. A channel, or the entry of one slot in `[slots]`, may have its own, see [Meters](channels/index.md#meters). |

Two more settings of the strips of applications are not here: `hold` (how long `apps` and `auto` keep an application)
and `exclude` (which ones they never take). They are in
[`[pool.apps]`](channels/applications.md#apps-and-auto).

```toml
[behavior]
max_volume = 150
encoder_step = 2
reset_volume = 100
```

### The volume scale

`max_volume` and `unity_at` together say what volume each point of the fader has. The scale printed next to the faders
marks 0 dB at about 77 % of the travel from the bottom, which is the default of `unity_at`. 0 dB means the volume
stays as the application sends it, which is 100 %, so the daemon puts 100 % there. From the bottom to that mark the fader goes from 0 to 100 %. From the mark to the top it goes from 100 % to
`max_volume`. Both parts are linear.

- With the default `max_volume = 130` the two parts have the same slope, because 100 / 130 is about 0.77: 100 % sits at 77 % of the
  travel. The fader is linear from 0 to 130 %.
- With a larger `max_volume` (up to 200) the part above the mark is steeper: the same distance covers more volume.
- With `max_volume = 100`, 100 % is at the top and `unity_at` is ignored.

Examples and a table are at [100 % at the 0 dB mark](channels/index.md#100-at-the-0-db-mark).

## `[aliases]`

The name that a strip shows for an application, in place of the name the sound server reports. It applies to every
strip that takes its application from the pools `apps` and `auto`, and to the pools of your own with `kind = "apps"`
([Applications](channels/applications.md#apps-and-auto)). An `apps` channel shows its `label` instead. An alias is
at most 7 characters of ASCII, because it must fit the LCD; a longer one is an error that `check-config` reports.

```toml
[aliases]
"WEBRTC VoiceEngine" = "Discord"
"Chromium" = "Browser"
```

The key is the application name the sound server reports, with the same upper and lower case. `xtouch-daemon list-apps`
shows it (and the alias it uses), and so do the suggestions of the GUI.

Next: [Commands](../reference/commands.md), [Troubleshooting](../guides/troubleshooting.md).
