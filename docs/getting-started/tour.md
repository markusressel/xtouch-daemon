# Setup tour

One configuration, built step by step: the one the author runs. Every step says what to click in the
[GUI](../guides/gui.md) and what it writes to the file. Use either; they edit the same file.

The goal, for the 8 strips (slots) of the X-Touch:

| Slot | Shows |
|---|---|
| 1 | The main output, with Select switching between phones, speakers and Bluetooth headphones. |
| 2, 3 | Slot 2 shows the browser and slot 3 the game, each while it plays. When it does not, the slot shows the next application that plays, and when there is none, a person of the voice chat. |
| 4 to 6 | A person of the voice chat each. People start at the right: the first person gets slot 6, the next slot 5, then slot 4. A slot without a person shows an application. |
| 7, 8 | VoIP on slot 7 and the microphone on slot 8 while you are in a call. Otherwise they show applications. |

You need the daemon installed and the X-Touch [set up and tested](first-steps.md), or the
[virtual one](without-a-device.md). Without a configuration file, the GUI (`xtouch-daemon gui`) edits a new, empty
one and writes it with the first "Save and apply". In an empty file every slot shows `auto`.

## 1. See what you have

```shell
xtouch-daemon list-devices    # outputs and inputs: the names to use as `device`
xtouch-daemon list-apps       # what plays now, and which preset it belongs to
```

Play something in the browser first. The GUI offers the same lists in every field that asks for an output, an input
or an application.

## 2. The main output

**GUI:** page **Channels**, **Add**, **Outputs** (under "From the sound server"), pick your speakers. Rename the id to
`main_output` (field next to the title; the slots that name it follow), set the label to `Main` (up to 7 characters:
that is all the LCD has) and the color to cyan.

Select should switch between several outputs, so add **Choices**, one per output. An output that exists only in
another profile of the sound card also needs the `card` and `profile`: `list-devices` prints both. Match Bluetooth
headphones with a wildcard, because their name holds their address:

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
profile = "output:iec958-stereo+input:analog-stereo"   # the card switches to this profile when you pick Speaker
max_volume = 200            # the fader reaches 200 % at the top for this output

[[channel.main_output.choices]]
label = "Buds"
device = "bluez_output.*"
```

See [Devices](../configuration/channels/devices.md#choices) for every option of choices.

## 3. Applications

**GUI:** **Add**, **Applications**. `match` names the applications or uses a
[preset](../configuration/presets.md) such as `@browsers`.

```toml
[channel.browser]
type = "apps"
match = ["@browsers"]
label = "Browser"
color = "blue"

[channel.game]
type = "apps"
match = ["@games"]
label = "Game"

[channel.voip]
type = "apps"
match = ["@voip"]
label = "VoIP"
color = "yellow"
lit_when_idle = true        # the LCD stays lit while no VoIP application plays, e.g. in a call that is quiet
```

## 4. The microphone

**GUI:** **Add**, **Inputs**, pick the microphone, then set the label and color.

```toml
[channel.mic]
type = "input"
device = "alsa_input.pci-0000_11_00.4.analog-stereo"
label = "Mic"
color = "red"
encoder = "balance"
```

## 5. A state: in a call

VoIP and the microphone should only take a strip while you are in a call, so make that a state. **GUI:** page
**States**, **Add**, **In a call**. Its sources are you in the voice chat ([Mumble](../guides/mumble.md),
[TeamSpeak](../guides/teamspeak.md)) and a recording application (Discord and the like have the microphone open
during a call):

```toml
[state.call]
voice_chat = true
recording = ["@voip"]
delay_off = 5               # stays on 5 s after the last source went off: a reconnect is not the end of the call
```

## 6. The slots

**GUI:** page **Slots**. Each slot is a card with its candidates. **+** adds one at the end; the inspector sets what
it shows ("Shows") and when ("When": empty is always). A new slot shows `auto`: change that candidate first, then
press **+** for the next.

```toml
[slots]
1 = "main_output"
# the browser and the game while they play, else the next application, else a person
2 = ["browser if present", "apps", "people"]
3 = ["game if present", "apps", "people"]
# people (the first on slot 6, then 5, then 4), else applications
4 = ["people", "apps"]
5 = ["people", "apps"]
6 = ["people", "apps"]
# VoIP and the microphone in a call, else applications
7 = ["voip if call", "apps"]
8 = ["mic if call", "apps"]
```

- `apps`, `people` and `auto` are [pools](../concepts.md#pools). A candidate with nothing to show hands the slot to
  the one below it.
- `present` is a ready-made condition: the channel of the candidate has something to control (for `browser`, a
  browser plays). `call` is the state of step 5.

## 7. Settings of the whole daemon

**GUI:** page **Settings**. The volume (in percent) a push on a `volume` encoder resets to, and a readable name for an
application:

```toml
[behavior]
reset_volume = 35

[aliases]
"WEBRTC VoiceEngine" = "Discord"
```

On **Settings**, **Extender**, the author picks the startup sequence `show` and sets `touchless_faders` for fader 1,
whose touch sensor is broken ([Behavior](../configuration/behavior.md#faders-without-a-touch-sensor)). On
**Channels**, the pool **People** lights the strips of people yellow:

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

The GUI shows the same on the page **Slots**: **Simulate** pretends another situation. **Save and apply** writes the
file, and a running daemon takes it at once. With no daemon running, "Install and start" at the top right starts the
systemd user service. See [GUI](../guides/gui.md).

The steps together are the whole file. Next: [Channels, states and slots](../configuration/slots.md) for what else a slot
can do, [Home Assistant](../guides/home-assistant.md), [Troubleshooting](../guides/troubleshooting.md).
