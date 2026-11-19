# Setup tour

One configuration, built step by step: the one the author runs. Every step says what to click in the
[GUI](../guides/gui.md) and what it writes to the file; use either, they edit the same file.

The goal, for the 8 strips (slots) of the device:

| Slot | Shows |
|---|---|
| 1 | The main output, with Select switching between phones, speakers and Bluetooth headphones. |
| 2, 3 | Slot 2 the browser and slot 3 the game, each while it plays; otherwise the next application that plays, otherwise a person of the voice chat. |
| 4 to 6 | People of the voice chat (from the right), otherwise applications. |
| 7, 8 | VoIP (7) and the microphone (8) while you are in a call; otherwise applications. |

You need the daemon installed and the device [set up and tested](first-steps.md). The GUI starts with
`xtouch-daemon gui`; without a configuration file it edits a new one and writes it with the first "Save and apply".
That new file is empty: every slot shows `auto`, the next application that plays. The drawing of the device at the top
shows what the file shows, as you edit.
No device? [Run the virtual one](without-a-device.md) and use that one as the device in this tour.

## 1. See what you have

```shell
xtouch-daemon list-devices    # outputs and inputs: the names to use as `device`
xtouch-daemon list-apps       # what plays now, and which preset (@browsers, @games, ...) it belongs to
```

The GUI offers the same lists wherever a field asks for a device or an application (the ▾ next to the field). Play
something in the browser first, so that `list-apps` has an application to show.

## 2. The main output

**GUI:** page **Channels**, **Add**, **Output from the sound server**, pick your speakers. Rename the id to
`main_output` (field next to the title; the slots that name it follow), set the label to `Main` (up to 7 characters:
that is all the LCD has) and the color to cyan.

Select should switch between several devices, so add **Choices**: one per device, each with a label. A device that
only exists in another profile of the sound card (the digital output, say) also needs the `card` and `profile`:
`list-devices` prints both. Bluetooth headphones are best matched by a wildcard, because their name holds their address
(`bluez_output.*`; `list-devices --snippet` writes it for you):

```toml
[channel.main_output]
type = "output"
color = "cyan"
label = "Main"

[[channel.main_output.choices]]
label = "Phones"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:analog-stereo+input:analog-stereo"

[[channel.main_output.choices]]
label = "Speaker"
device = "alsa_output.pci-0000_11_00.4.iec958-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:iec958-stereo+input:analog-stereo"   # keeps the microphone (analog input) alive
max_volume = 200

[[channel.main_output.choices]]
label = "Buds"
device = "bluez_output.*"
```

See [Devices](../configuration/channels/devices.md#choices) for every option of choices.

## 3. Applications

**GUI:** **Add**, **Applications**. An `apps` channel is a group of applications that gets one strip: `match` names
them (by a part of their name or program) or uses a preset such as `@browsers`, `@voip` or `@games`, which come with
the daemon ([Presets](../configuration/presets.md)).

```toml
[channel.browser]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "blue"
meter = true

[channel.game]
type = "apps"
match = ["@games"]
label = "Game"

[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "yellow"
lit_when_idle = true        # the LCD stays lit while nothing plays: it is where the voice chat goes
```

## 4. The microphone

**GUI:** page **Channels**, **Add**, **Input from the sound server**, pick the microphone, then give it the label and the
color.

```toml
[channel.mic]
type = "input"
device = "alsa_input.pci-0000_11_00.4.analog-stereo"
label = "Mic"
color = "red"
encoder = "balance"
```

## 5. A state: in a call

A *state* is when something matters. VoIP and the microphone should only take a strip while you are in a call, so
make that a state. **GUI:** page **States**, **Add**, **In a call (state)**; its sources are "You are in the voice chat"
(Mumble, with its [plugin](../guides/mumble.md)) and "An application records" (Discord and the like have the
microphone open while you talk):

```toml
[state.call]
voice_chat = true
recording = ["@voip"]
delay_off = 5               # stays on 5 s after the last source went off: a reconnect is not the end of the call
```

## 6. The slots

**GUI:** page **Slots**. Each slot is a card with its candidates, the first whose condition holds is shown. **+** adds a
candidate at the end; pick one and the inspector sets what it shows ("Shows") and when ("When": empty is always, or a
condition such as `call`, `present`, `call and not gaming`). Pick a slot's first candidate before adding the next: an
empty slot is `auto`, so the first **+** shows it as a candidate you can change.

```toml
[slots]
1 = "main_output"
# the browser and the game while they play, else the next application, else a person
2 = ["browser if present", "apps", "people"]
3 = ["game if present", "apps", "people"]
# people from the right (6, 5, 4), else applications
4 = ["people", "apps"]
5 = ["people", "apps"]
6 = ["people", "apps"]
# VoIP and the microphone in a call, else applications
7 = ["voip if call", "apps"]
8 = ["mic if call", "apps"]
```

- `apps` is the next application that plays and has no channel; `people` the next person of the voice chat;
  `auto` is both. A candidate that has nothing to show hands the slot to the one below it.
- `present` means the candidate's own channel has something to control: the browser is playing.
- Anything you leave out is `auto`.

## 7. Settings of the whole daemon

**GUI:** page **Settings**. The author lowers the volume a push on an encoder resets to, and renames an application
that calls itself something unreadable:

```toml
[behavior]
reset_volume = 35

[aliases]
"WEBRTC VoiceEngine" = "Discord"
```

Three more settings finish the file. On **Settings**, **Extender**, the author picks the startup sequence `show` and
switches fader 1 to `touchless_faders`, because its touch sensor is broken and the fader jumps back after every move
([Behavior](../configuration/behavior.md#faders-without-a-touch-sensor)). On **Channels**, in the built-in pool
**People**, the strips of people light up yellow:

```toml
[device]
touchless_faders = [1]
startup = "show"

[pool.people]
color = "yellow"
```

## 8. Check it, then apply it

```shell
xtouch-daemon check-config     # errors with the line they are in, then what every slot shows when
```

A long table shows the situations that change one thing; `check-config --all` has every combination.

The GUI shows the same on the page **Slots**: **Simulate** puts the device in another situation (in a call, nothing
playing, a game running) and the drawing shows what the strips would show, on a virtual twin of the device in the daemon (so Simulate needs
the running daemon).

**Save and apply** writes the file. A running daemon takes it at once; otherwise the button next to the service at the
top right ("Install and start") starts it as a systemd user service, so it is there from your next login on.

## Whole file

```toml
[device]
touchless_faders = [1]
startup = "show"

[behavior]
reset_volume = 35

[aliases]
"WEBRTC VoiceEngine" = "Discord"

[channel.main_output]
type = "output"
color = "cyan"
label = "Main"

[[channel.main_output.choices]]
label = "Phones"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:analog-stereo+input:analog-stereo"

[[channel.main_output.choices]]
label = "Speaker"
device = "alsa_output.pci-0000_11_00.4.iec958-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:iec958-stereo+input:analog-stereo"
max_volume = 200

[[channel.main_output.choices]]
label = "Buds"
device = "bluez_output.*"

[channel.browser]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "blue"
meter = true

[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "yellow"
lit_when_idle = true

[channel.mic]
type = "input"
device = "alsa_input.pci-0000_11_00.4.analog-stereo"
label = "Mic"
color = "red"
encoder = "balance"

[channel.game]
type = "apps"
match = ["@games"]
label = "Game"

[pool.people]
color = "yellow"

[state.call]
voice_chat = true
recording = ["@voip"]
delay_off = 5

[slots]
1 = "main_output"
2 = ["browser if present", "apps", "people"]
3 = ["game if present", "apps", "people"]
4 = ["people", "apps"]
5 = ["people", "apps"]
6 = ["people", "apps"]
7 = ["voip if call", "apps"]
8 = ["mic if call", "apps"]
```

Where to go from here: [Channels, states and slots](../configuration/slots.md) for what else a slot can do (pools, modes,
controls), [Home Assistant](../guides/home-assistant.md), [Troubleshooting](../guides/troubleshooting.md).
