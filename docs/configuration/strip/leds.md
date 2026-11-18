# LEDs

Every strip has four buttons with LEDs: Rec, Solo, Mute and Select.

| LED | On audio strips |
|---|---|
| Mute | On while the strip is muted. |
| Select | On device strips with `device` and `select`: on while the device is the default. Otherwise off. |
| Rec | An indicator (option `rec`). On device strips with [profiles](../channels/devices.md#profiles) it shows the profile instead: on for every profile but the first. |
| Solo | An indicator (option `solo`). |

On `homeassistant` strips every LED is an entity that Home Assistant sets, see
[Home Assistant](../../guides/home-assistant.md#entities).

## Indicators

The Rec and Solo LEDs are indicators; their buttons do nothing (except Rec with profiles). Each shows one of:

| Indicator | Lit while |
|---|---|
| `recording` | An application records: from the input, from the monitor of the output (e.g. a screen recorder), or for `apps`/`auto` strips, the application records anything (e.g. Discord using a microphone). Level meters don't count: the daemon's own, pavucontrol's. |
| `playing` | Audio flows: the device runs, or a stream of the applications plays. |
| `default` | The device is the default output/input. Never for applications. |
| `muted` | The strip is muted (like the Mute LED). |
| `off` | Never: the LED stays dark. |

| Option | Default |
|---|---|
| `rec` | `"recording"` |
| `solo` | `"off"` |

```toml
[channel.mic]
type = "input"
label = "Mic"
rec = "recording"   # the default: lit while an application uses the microphone
solo = "default"
```
