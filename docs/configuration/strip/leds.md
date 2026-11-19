# Buttons and LEDs

Every strip has four buttons with LEDs: Rec, Solo, Mute and Select. Mute mutes the strip, and its LED is on while
the strip is muted. What the other three do, and what their LEDs show, is up to you.

| Button | By default |
|---|---|
| Select | On device strips with `device` or `choices`: makes the device the default; its LED is on while it is. On application strips with `launch`: starts the application; its LED flashes while it starts and is on while it runs. Otherwise nothing. |
| Rec | On device strips with [profiles](../channels/devices.md#profiles): switches the sound card to the next profile; its LED is on for every profile but the first. Otherwise nothing, and its LED is lit while an application records (`recording`). |
| Solo | Nothing; its LED stays dark. |

On `homeassistant` strips every LED is an entity that Home Assistant sets, see
[Home Assistant](../../guides/home-assistant.md#entities).

## Buttons

Each of `select`, `rec` and `solo` takes a table: what a press does, what a hold does and what the LED shows. A part
you leave out does what the strip type does by default.

```toml
[channel.main]
type = "output"
device = ["alsa_output.*", "bluez_output.*"]

[channel.main.select]
press = "default"   # makes the device shown the default; on the default one, the next one
hold = "next"       # shows (and controls) the next device, the default stays
led = "shown"       # lit while the strip shows another device than the default

[channel.main.solo]
press = "mute_others"   # while held, the other strips are muted
```

| Option | Default | What it does |
|---|---|---|
| `press` | what the type does | What a press does, see [Actions](#actions). |
| `hold` | `"off"` | What holding the button for longer than half a second does. With a hold, a press acts when you let go of the button; without one, it acts at once. |
| `led` | what the type shows | What the LED shows, see [What the LED shows](#what-the-led-shows). |

`select = true` and `select = false` are short for Select doing what the type does, or nothing.
`rec = "playing"` (an indicator alone) is short for `rec = { led = "playing" }`.

A place in `[slots]` can set what an LED shows (`{ show = "devices", rec = "playing" }`), not what a button does:
that belongs to the channel. The buttons of a slot that act whatever the slot shows are
[`[controls]`](../slots.md#controls-and-the-chord). On the strips of the chord, Solo does the chord too.

### Actions

| Action | For | Does |
|---|---|---|
| `default` | output, input with `device` or `choices` | Makes the device shown the default. On the default one, the next one of `device` or `choices`. |
| `next` | output, input with `device` or `choices` | The strip shows (and controls) the next device that is there; the default stays. Until the default changes. |
| `profile` | output, input with `profiles` | Switches the sound card to the next of `profiles`. |
| `launch` | apps, auto with `launch` | Starts `launch`. |
| `talk` | input | Mute is off while the button is held: push to talk. |
| `mute_others` | all | The other strips are muted while the button is held, and unmuted again when you let go. |
| `homeassistant` | all | An event in Home Assistant for each press and release (`select_pressed`, `select_released`, ...). Needs [`[mqtt]`](../../guides/home-assistant.md). As `press` only. |
| `cycle_modes` | all | The next mode, as the chord picks it. |
| `mode:<id>` | all | Picks the mode. |
| `toggle:<id>` | all | Turns the state or mode on, and the next time gives it back to its sources. |
| `{ launch = [...] }` | all | Starts the program, like a launch of [`[controls]`](../slots.md#controls-and-the-chord). `launch_when_running = true` starts it also while it runs. |
| `off` | all | Nothing. |

`talk`, `mute_others` and `homeassistant` last while the button is held: they take no `hold`.

### What the LED shows

`led` takes an [indicator](#indicators), or:

| Value | Lit while |
|---|---|
| `press` | What a press does is so: the device is the default (`default`), the card is in another profile than the first (`profile`), the application runs (`launch`), the mode or state is on, the button is held (`talk`, `mute_others`). |
| `shown` | The strip shows another device than the default one (after `next`). |

## Indicators

| Indicator | Lit while |
|---|---|
| `recording` | An application records: from the input, from the monitor of the output (e.g. a screen recorder), or for `apps`/`auto` strips, the application records anything (e.g. Discord using a microphone). Level meters don't count: the daemon's own, pavucontrol's. |
| `playing` | Audio flows: the device runs, or a stream of the applications plays. |
| `default` | The device is the default output/input. Never for applications. |
| `muted` | The strip is muted (like the Mute LED). |
| `off` | Never: the LED stays dark. |

```toml
[channel.mic]
type = "input"
label = "Mic"
rec = "recording"   # the default: lit while an application uses the microphone
solo = { press = "talk", led = "muted" }
```
