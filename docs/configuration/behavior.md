# Behavior, device and aliases

The sections that apply to the daemon and to every strip. The GUI shows them in the tab "Global settings".

## `[device]`

| Option | Default | Meaning |
|---|---|---|
| `name` | `"X-Touch-Ext"` | Part of the name of the extender's sound card, as `/proc/asound/cards` lists it. |

A changed `[device]` section needs a restart of the daemon.

## `[behavior]`

| Option | Default | Meaning |
|---|---|---|
| `max_volume` | `100` | The volume of a fader at the top, 100..200 percent. Above 100 % the audio is amplified in software. Strips may have their own [range](strips.md#volume-range). |
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
