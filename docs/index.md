# xtouch-daemon

xtouch-daemon turns a Behringer X-Touch Extender into a hardware mixer for PipeWire on Linux. Its motor faders, LED
meters and scribble strips control your devices, your applications and the people of your voice chat. A strip can
also belong to Home Assistant instead, for lights, speakers in other rooms or scenes. To use it for real, you need the extender (in MC
mode, on USB) and a Linux desktop with PipeWire; there is no Windows or macOS version.

![The GUI: the device as it is, the slots and the inspector of the slot picked](images/gui.png)

## How it works

The device has 8 strips, and the configuration has a **slot** for each. A slot is a list of the things its strip can control, such as a device or an application.
The daemon shows the first entry of the list whose condition is true. An entry without a condition is always true, so
it is the fallback at the end. A condition is written with **states**, such as "gaming" or "in a call", which are on or off. You define a state
in the same file, from what the daemon can see: a program that runs, an application that plays, a device that is
connected, your presence in the voice chat. The word `present` is not a state. It is a ready-made condition that needs no definition: it
is true while the channel has something to control: for `buds`, while the headphones are connected.

Here is a small configuration with two slots:

```toml
[channel.buds]                  # a channel: you define it, and it controls one thing
type = "output"
device = "bluez_output.*"       # any Bluetooth headphones

[channel.game]
type = "apps"                   # every sound stream of some applications
match = ["@steam-games"]        # a preset: the games started from Steam
label = "Game"                  # the top line of the LCD

[state.gaming]                  # a state: on while a Steam game runs
processes = ["@steam-games"]

[slots]
1 = ["buds if present", "auto"]   # the buds while they are connected, else the next application or person
2 = ["game if gaming", "auto"]    # the game while you play, else the next application or person
```

Each entry of a slot is a channel or a pool:

- A **channel** is one thing you define, such as your headphones, a group of applications, a person or a strip for
  Home Assistant. It always takes exactly one strip.
- A **pool** fills strips by itself, so you don't list what is in it. The four pools are:
    - `apps` hands out the applications that play, one per strip. An application whose channel has a slot of its
      own appears there instead.
    - `people` hands out the people of your voice chat.
    - `auto` hands out the applications and the people together.
    - `devices` hands out the sound devices that have no channel of their own.

In the example above, `buds` and `game` are channels, `gaming` is a state, and `auto` is a pool.

So the device follows what you do: the game gets a fader while it runs, the voice chat while you are in a call, and the next application that plays takes a free strip. When a strip changes, the other strips keep what they show, and a strip you are touching keeps what it shows until you let go.

To install it and try it, start with [Getting started](getting-started/install.md). [Concepts](concepts.md) explains
each of these words and the ones that look alike.

## What a strip can control

- **Devices** (`output`, `input`): one sound output or input: a device you name, the first of several that is connected, or the system default. With
  a list of `choices`, the Select button of the strip switches between devices, e.g. headphones, speakers and
  Bluetooth buds. See
  [Devices](configuration/channels/devices.md).
- **Applications** (`apps`): every stream of a group of applications at once, e.g. every browser, with
  [presets](configuration/presets.md) for browsers, voice chats, games, music and video players. Select can start the
  application, if you give the channel a `launch` command. See [Applications](configuration/channels/applications.md).
- **The people of the voice chat**: a strip per person in your Mumble or TeamSpeak channel, with their name, their
  voice on the meter and their volume on the fader. See [People](configuration/channels/people.md),
  [Mumble](guides/mumble.md) and [TeamSpeak](guides/teamspeak.md).
- **Home Assistant**: a strip whose fader, encoder, LCD, LEDs and buttons are entities for your automations, e.g. to
  dim a light or set the volume of a speaker in another room. See [Home Assistant](guides/home-assistant.md).
- **Custom** (`custom`): something other than audio, e.g. the brightness of a screen, with each part of the strip
  connected to a command of your own. See [Custom channels](configuration/channels/custom.md).

Every strip has a motor fader that glides to new values and stays still under your finger, a volume range up to 200 %,
an LCD with a label and the volume, an encoder (a rotary knob that you turn and push; it sets the balance or the volume, picks an application or controls
the media player),
LEDs for Mute, Select, Rec and Solo, and a level meter that never wakes a device or switches Bluetooth headphones
into headset mode. See [Encoders](configuration/strip/encoders.md) and [Buttons and LEDs](configuration/strip/leds.md).

## Tools

- **A GUI** (`xtouch-daemon gui`, or `xtouch-daemon-gui` with the Arch Linux package): the device as it is right now, every option with its help and errors, suggestions
  from the sound server, Simulate (what the slots show in another situation), and a preview of the changes, in the
  window or on the device, before you save. See [GUI](guides/gui.md).
- **No device needed to start**: a virtual device stands in for it. See
  [Without a device](getting-started/without-a-device.md).
- **Command line**: a device test, a check of the configuration with a table of what the slots show when, and why a
  slot shows what it shows. See [Commands](reference/commands.md).
- **A systemd user service** that recovers when the device is unplugged or the sound server restarts, applies a
  changed configuration without a restart, and leaves the device dark when it stops.

## Requirements

- Linux with PipeWire and its PulseAudio server `pipewire-pulse`. Plain PulseAudio is not enough, because the meters need
  `pw-record` from PipeWire.
- `pw-record` for the meters. It comes with PipeWire; you install nothing extra.
- Python 3.14. You don't install it yourself: the Arch Linux package brings its own, and `uv` installs it when you
  [install from the source](getting-started/install.md).
- A Behringer X-Touch Extender set to **MC** (Mackie Control) mode and connected by **USB**; [Getting
  started](getting-started/first-steps.md#set-up-the-device) shows how to set it.
- For Home Assistant: an MQTT broker that Home Assistant also uses (e.g. the Mosquitto add-on). The daemon talks to Home Assistant through it.

## Where to go next

| Section | What it covers |
|---|---|
| [Getting started](getting-started/install.md) | Install, set up and test the device, write a first configuration, run the service; or try it [without a device](getting-started/without-a-device.md). Start here. |
| [Concepts](concepts.md) | Channels, slots, states, pools and the words that look alike. |
| Guides | The [GUI](guides/gui.md), [Home Assistant](guides/home-assistant.md), [Mumble](guides/mumble.md), [TeamSpeak](guides/teamspeak.md), and [Troubleshooting](guides/troubleshooting.md). |
| [Configuration](configuration/index.md) | The file, applying changes, and every option: [channels, states and slots](configuration/slots.md), the [channel types](configuration/channels/index.md), the parts of a strip. |
| Reference | Every [command](reference/commands.md), the [hardware and its protocol](reference/hardware.md), the [voice chat bridge](reference/voice-chat-bridge.md). |
