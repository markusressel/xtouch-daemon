# Setup tour

One configuration, built step by step: the one the author runs. Every step says what to click in the
[GUI](../guides/gui.md) and what it writes to the file; use either, they edit the same file.

The goal, for the 8 strips (slots) of the X-Touch:

| Slot | Shows |
|---|---|
| 1 | The main output, with Select switching between phones, speakers and Bluetooth headphones. |
| 2, 3 | Slot 2 shows the browser and slot 3 the game, each while it plays. When it does not, the slot shows the next application that plays, and when there is none, a person of the voice chat. |
| 4 to 6 | A person of the voice chat each. People start at the right: the first person gets slot 6, the next slot 5, then slot 4. A slot without a person shows an application. |
| 7, 8 | VoIP on slot 7 and the microphone on slot 8 while you are in a call. Otherwise they show applications. |

You need the daemon installed and the X-Touch [set up and tested](first-steps.md). The GUI starts with
`xtouch-daemon gui`; without a configuration file it edits a new one and writes it with the first "Save and apply".
That new file is empty: every slot shows `auto`, the next application that plays (or a person of the voice chat). The
drawing of the X-Touch at the top shows what the file shows, as you edit. No X-Touch? [Run the virtual
one](without-a-device.md) and use it in this tour.

## 1. See what you have

```shell
xtouch-daemon list-devices    # outputs and inputs: the names to use as `device`
xtouch-daemon list-apps       # what plays now, and which preset (a ready-made group of applications, e.g. `@browsers` or `@games`) it belongs to
```

The GUI offers the same lists wherever a field asks for an output, an input or an application (a click into the field opens them). Play
something in the browser first, so that `list-apps` has an application to show.

## 2. The main output

**GUI:** page **Channels**, **Add**, **Outputs** (under "From the sound server"), pick your speakers. Rename the id to
`main_output` (field next to the title; the slots that name it follow), set the label to `Main` (up to 7 characters:
that is all the LCD has) and the color to cyan.

Select should switch between several outputs, so add **Choices**: one per output, each with a label. An output that
exists only in another profile of the sound card (a profile is a setting of the card, such as analog or digital
output) also needs the `card` and `profile`: `list-devices` prints both. Bluetooth headphones are best matched by a
wildcard, because their name holds their address (`bluez_output.*`; `list-devices --snippet` writes it for you):

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

**GUI:** **Add**, **Applications**. An `apps` channel is a group of applications that gets one strip: `match` names
them (by a part of their name or program) or uses a preset such as `@browsers`, `@voip` or `@games`, which come with
the daemon ([Presets](../configuration/presets.md)).

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

**GUI:** page **Channels**, **Add**, **Inputs** (under "From the sound server"), pick the microphone, then give it the label and the
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

A *state* is a fact about your situation that is either on or off, such as "I am in a call". VoIP and the microphone should only take a strip while you are in a call, so
make that a state. **GUI:** page **States**, **Add**, **In a call** (under "Starting points"); its sources are "You are in the voice chat"
(Mumble or TeamSpeak, with their plugins: [Mumble](../guides/mumble.md), [TeamSpeak](../guides/teamspeak.md)) and "An application records" (`recording`: Discord and the like have the
microphone open while you talk, so a recording application counts as a call):

```toml
[state.call]
voice_chat = true
recording = ["@voip"]
delay_off = 5               # stays on 5 s after the last source went off: a reconnect is not the end of the call
```

## 6. The slots

**GUI:** page **Slots**. Each slot is a card with its candidates, the first whose condition holds is shown. **+** adds a
candidate at the end; pick one and the inspector sets what it shows ("Shows") and when ("When": empty is always, or a
condition such as `call`, `present`, `call and not gaming`). A slot you have not edited shows `auto`: change that
candidate to what you want first, then press **+** for the next one.

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

- `apps` is the next application that plays and has no channel. `people` is the next person of the voice chat. `auto`
  is both together. A candidate that has nothing to show hands the slot to the one below it.
- `present` is a ready-made condition, not a state. It means that the channel of this candidate has something to
  control: for `browser`, a browser is playing. `call` is the state you defined in step 5.
- A single name without a list, such as `1 = "main_output"`, is a slot with one candidate that always shows.
- A slot you leave out is `auto`.

## 7. Settings of the whole daemon

**GUI:** page **Settings**. The author sets the volume (in percent) that a push on a `volume` encoder resets to, and
renames an application that calls itself something unreadable:

```toml
[behavior]
reset_volume = 35

[aliases]
"WEBRTC VoiceEngine" = "Discord"
```

Three more settings finish the file. On **Settings**, **Extender**, the author picks the startup sequence `show` and
switches fader 1 to `touchless_faders`, because its touch sensor is broken and the fader jumps back after every move
([Behavior](../configuration/behavior.md#faders-without-a-touch-sensor)). On **Channels**, in the pool
**People** (a built-in pool: it is there without you adding it), the strips of people light up yellow, as the settings
`[pool.people]` say:

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

The table lists the situations in which something changes, for example "in a call".

The GUI shows the same on the page **Slots**: **Simulate** pretends another situation (in a call, nothing
playing, a game running), and the drawing shows what the strips would show. The preview "On the device" shows it on the
X-Touch itself.

**Save and apply** writes the file. A running daemon takes it at once. If no daemon runs, the button "Install and
start" next to the service at the top right installs and starts the systemd user service now, and it starts again at
every login.

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
