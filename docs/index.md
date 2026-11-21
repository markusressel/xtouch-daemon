# xtouch-daemon

xtouch-daemon turns a Behringer X-Touch Extender into a hardware mixer for PipeWire on Linux. Its motor faders, LED
meters and scribble strips control your headphones, your applications and the people of your voice chat. A strip can
also belong to Home Assistant, for lights, speakers in other rooms or scenes.

![The GUI: the X-Touch as it is, the slots and the inspector of the slot picked](images/gui.png)

## How it works

The X-Touch has 8 strips, and the configuration has a **slot** for each. A slot is a list of the things its strip
can control. The strip shows the first entry whose condition is true. A condition uses **states**, such as "gaming"
or "in a call", which you define from what the daemon sees: a program that runs, headphones that connect, you in the
voice chat.

```toml
[channel.buds]                  # a channel: what one strip controls
type = "output"
device = "bluez_output.*"       # your Bluetooth headphones; with two pairs, Select switches

[channel.game]
type = "apps"                   # every sound stream of some applications
match = ["@steam-games"]        # a preset: the games started from Steam

[state.gaming]                  # a state: on while a Steam game runs
processes = ["@steam-games"]

[slots]
1 = ["buds if present", "auto"]   # the buds while they are connected, else the next application or person
2 = ["game if gaming", "auto"]    # the game while you play, else the next application or person
```

`buds` and `game` are channels, `gaming` is a state, and `auto` is a pool: it fills strips by itself with the
applications that play and the people of your voice chat. [Concepts](concepts.md) explains each word.

## What a strip can control

- **Outputs and inputs**: headphones, speakers, a microphone; Select switches between several. See
  [Devices](configuration/channels/devices.md).
- **Applications**: all streams of a group of applications, e.g. every browser. See
  [Applications](configuration/channels/applications.md).
- **People of the voice chat**: Mumble or TeamSpeak. See [People](configuration/channels/people.md).
- **Home Assistant**: a strip whose parts are entities for your automations. See
  [Home Assistant](guides/home-assistant.md).
- **Custom**: something other than audio, e.g. screen brightness. See
  [Custom channels](configuration/channels/custom.md).

## Tools

- A [GUI](guides/gui.md) shows the X-Touch live, with every option, a Simulate of other situations and a preview
  before you save.
- A [command line](reference/commands.md) tests the X-Touch, checks the configuration and explains what a slot shows.
- A systemd user service keeps the daemon running and applies a changed configuration without a restart.

## Requirements

- Linux with PipeWire and `pipewire-pulse`. Plain PulseAudio is not enough: the meters need `pw-record`.
- Python 3.14 (the Arch Linux package brings its own, `uv` installs it for a [source install](getting-started/install.md)).
- An X-Touch Extender in **MC** mode on **USB**: [First steps](getting-started/first-steps.md#set-up-the-device). No
  X-Touch yet? A [virtual one](getting-started/without-a-device.md) stands in.
- For Home Assistant: an MQTT broker that Home Assistant also uses.

There is no Windows or macOS version.

## Where to go

| I want to | Go to |
|---|---|
| Install, set up the X-Touch, run the service | [Getting started](getting-started/install.md) |
| Build a whole configuration step by step | [Setup tour](getting-started/tour.md) |
| Understand channels, slots, states, pools | [Concepts](concepts.md) |
| Edit in a window, with Simulate and preview | [GUI](guides/gui.md) |
| Use Home Assistant, Mumble or TeamSpeak | [Home Assistant](guides/home-assistant.md), [Mumble](guides/mumble.md), [TeamSpeak](guides/teamspeak.md) |
| Fix a problem | [Troubleshooting](guides/troubleshooting.md) |
| Look up an option | [Configuration](configuration/index.md): [slots](configuration/slots.md), [channel types](configuration/channels/index.md), [strip parts](configuration/strip/encoders.md) |
| Look up a command or the protocol | [Commands](reference/commands.md), [hardware](reference/hardware.md), [voice chat bridge](reference/voice-chat-bridge.md) |
