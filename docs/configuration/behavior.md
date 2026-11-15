# Behavior, device and aliases

The sections that apply to the daemon and to every strip. The GUI shows them in the tab "Global settings".

## `[device]`

| Option | Default | Meaning |
|---|---|---|
| `name` | `"X-Touch-Ext"` | Part of the name of the extender's sound card, as `/proc/asound/cards` lists it. |
| `touch_required` | `true` | Whether a fader changes a value only while the device reports a touch. `false` makes every move count, see [below](#faders-without-a-touch-sensor). |
| `touchless_faders` | `[]` | Faders whose touch sensor does not work, numbered from 1 on the left, see [below](#faders-without-a-touch-sensor). |
| `startup` | `"sweep"` | How the strips light up after a connect, see [below](#startup-and-shutdown-sequences). |
| `shutdown` | `"sweep"` | How the strips go dark when the daemon stops, see [below](#startup-and-shutdown-sequences). |

A changed `name` needs a restart of the daemon; a reload takes the others.

### Startup and shutdown sequences

After a connect the strips light up and their faders come up to their values; when the daemon stops, the strips go
dark and their faders go down. `startup` and `shutdown` choose how:

| Value | Startup | Shutdown |
|---|---|---|
| `instant` | All strips at once. | All strips at once. |
| `sweep` | One after the other from the left, 80 ms apart. | One after the other from the right. |
| `curtain` | From the middle outwards, pair by pair (4 and 5 first, 1 and 8 last). | From the outside in. |
| `show` | A wave of light runs across from the left: each strip lights up white with all its buttons, its meter jumps to the top and falls, its ring fills up. Behind the wave the strips show what they are, about 1.2 s after the connect. | From the right, each strip flashes white, its meter jumps to the top and its ring drains; then it goes dark. |

```toml
[device]
startup = "show"
shutdown = "curtain"
```

### Faders without a touch sensor

Only a touched fader changes a value (see [Hardware](../hardware.md#motor-faders)), so a fader whose touch sensor
failed goes back to its value shortly after every move. Until it is repaired, `touchless_faders` lets it work without the
sensor: a move counts as a touch, and half a second without a move as letting go. In the GUI these are the buttons
under "Touchless faders" on the page "Device".

```toml
[device]
touchless_faders = [1]   # the touch sensor of fader 1 is broken
```

`touch_required = false` does the same for all faders. The touch sensor does not notice everything that moves a fader
on purpose, e.g. a fingertip pushing it from below; with it off, such a push counts too.

```toml
[device]
touch_required = false   # every move of a fader counts
```

What it can't do:

- **Resting fingers:** a finger that rests on the fader without moving it counts as gone after half a second. The
  fader then goes to its value, which is where the finger left it, so you notice nothing, unless the value changes
  elsewhere meanwhile.
- **The first 3 seconds after a connect:** after it was switched on, the device moves its faders down by itself. So in
  the first 3 seconds after the device was connected, a move counts only with a touch, like on the other faders.

## `[behavior]`

| Option | Default | Meaning |
|---|---|---|
| `max_volume` | `130` | The volume of a fader at the top, 100..200 percent. Above 100 % the audio is amplified in software. 130 puts 100 % at the 0 dB mark of the device with one slope over the whole travel; 100 puts it at the top. Strips may have their own [range](strips.md#volume-range). |
| `unity_at` | `77` | Where on the fader 100 % is, 10..95 percent of the travel; the device marks 0 dB at about 77. For strips whose range goes above 100 %, see [100 % at the 0 dB mark](strips.md#100-at-the-0-db-mark). |
| `encoder_step` | `1` | Percent per encoder step, 1..10. Used by the `volume` [encoder](encoders.md) and by the encoders of `homeassistant` strips. |
| `reset_volume` | `100` | The volume a push on a `volume` encoder sets, 0..200, at most `max_volume`. It stays within the range of the strip. |
| `meters` | `true` | Whether the LED meters show audio levels at all. |
| `auto_hold` | `5` | Seconds an `auto` strip keeps an application after it stopped playing. |
| `ignore` | `["speech-dispatcher"]` | Applications `auto` strips never take: parts of the name or binary, ignoring case. |

```toml
[behavior]
max_volume = 150
encoder_step = 2
reset_volume = 100
auto_hold = 10
ignore = ["speech-dispatcher", "notification"]
```

## `[aliases]`

The name to show on an `auto` strip for an application, at most 7 characters of ASCII:

```toml
[aliases]
"WEBRTC VoiceEngine" = "Discord"
"Firefox" = "Firefox"
```

The key is the application name the sound server reports. `xtouch-daemon list-apps` shows it, and so do the
suggestions of the GUI.
