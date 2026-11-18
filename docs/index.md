# xtouch-daemon

xtouch-daemon turns a Behringer X-Touch Extender into a hardware mixer for PipeWire on Linux. Its motor faders, LED
meters and scribble strips control your devices, your applications and the people of your voice chat. A strip can
also belong to Home Assistant instead, for lights, speakers in other rooms or scenes.

![The GUI: the device as it is, the slots and the inspector of the slot picked](images/gui.png)

## What it does

You describe **channels**, the things a strip can control: an output or input, a group of applications, a person
in the voice chat, or a strip for Home Assistant. Each of the 8 strips of the device is a **slot** with a short list
of channels it can show, and **states** (in a call, gaming) decide which one it shows now. So the device follows what
you do: the game gets a fader while it runs, the voice chat and the microphone while you are in a call, and the next
application that plays takes a free strip. When one strip changes, the others stay as they are, and a strip you
are touching or pressing (a fader, a button, the encoder) keeps what it shows until you let go. See [Channels, states and slots](configuration/slots.md).

### What a strip can control

- **Devices** (`output`, `input`): an output or input, whichever of several is there (`bluez_output.*`), or the
  default one. Select makes it the default; with `choices` Select switches between devices, e.g. headphones,
  speakers and Bluetooth buds, also switching the profile of the sound card. See
  [Devices](configuration/channels/devices.md).
- **Applications** (`apps`): every stream of a group of applications at once, e.g. every browser, with
  [presets](configuration/presets.md) for browsers, voice chats, games, music and video players. Select can start the
  application. See [Applications](configuration/channels/applications.md).
- **Whatever plays**: the built-in `auto` and `apps` take the next application that plays and has no strip of its
  own, and keep it a few seconds after it stops; the encoder picks another one, a push pins it.
- **The people of the voice chat**: a strip per person in your Mumble channel, with their name, their voice on the
  meter and their volume on the fader. See [People](configuration/channels/people.md) and [Mumble](guides/mumble.md).
- **Home Assistant**: a strip whose fader, encoder, LCD, LEDs and buttons are entities for your automations, e.g. to
  dim a light or set the volume of a speaker in another room. Any slot can also hand a single control to Home
  Assistant. See [Home Assistant](guides/home-assistant.md).

### On every strip

- **Motor faders** glide to new values, follow changes made anywhere else, and stay still while your finger is on
  them. Only a touched fader changes a value.
- **Volume ranges** up to 200 % (amplified in software), with 100 % at the 0 dB mark of the device.
- **The LCD** shows a label and the volume (or `muted`, `idle`, `off`) on a backlight in the strip's color; a strip
  with nothing to control goes dark.
- **The encoder** sets the balance or the volume in fine steps, picks the application, or seeks and plays or pauses
  the media player; its LED ring shows it. See [Encoders](configuration/strip/encoders.md).
- **LEDs**: Mute, Select for the default device, and Rec and Solo as indicators (recording, playing, default, muted).
  See [LEDs](configuration/strip/leds.md).
- **Meters** show the level before or after the fader and light the red LED when the audio clips. They are passive:
  they never wake a device, light your desktop's microphone indicator or switch Bluetooth headphones into headset mode.

### Around it

- **A GUI** (`xtouch-daemon gui`): the device as it is right now, every option with its help and errors, suggestions
  from the sound server, Simulate (what the slots show in another situation), "Try on the device" before you save,
  Play (the mouse as a hand on the device), undo, and saving that keeps the comments of the file. See
  [GUI](guides/gui.md).
- **No device needed to start**: a virtual device stands in for it, in the GUI or headless. See
  [Without a device](getting-started/without-a-device.md).
- **Command line tools**: a device test, the devices, profiles and applications there are, a check of the
  configuration with a table of what the slots show when, and why a slot shows what it shows. See
  [Commands](reference/commands.md).
- **Robust**: survives unplugging or switching off the device and restarts of the sound server and the MQTT broker,
  and shows everything again when they are back.
- **A proper service**: a systemd user service (`Type=notify`), a reload applies a changed configuration without a
  restart, the log goes to the journal. When it stops, it leaves the device dark.

## Requirements

- Linux with PipeWire and `pipewire-pulse` (or PulseAudio).
- `pw-record` (part of PipeWire) for the meters.
- Python 3.14 (the Arch Linux package brings its own).
- A Behringer X-Touch Extender in **MC** mode on **USB** (see [Getting started](getting-started/first-steps.md#set-up-the-device)).
- For Home Assistant: an MQTT broker that Home Assistant uses (e.g. the Mosquitto add-on).

## Where to go next

| Section | What it covers |
|---|---|
| [Getting started](getting-started/install.md) | Install, set up and test the device, write a first configuration, run the service; or try it [without a device](getting-started/without-a-device.md). Start here. |
| Guides | The [GUI](guides/gui.md), [Home Assistant](guides/home-assistant.md), [Mumble](guides/mumble.md), and [Troubleshooting](guides/troubleshooting.md). |
| [Configuration](configuration/index.md) | The file, applying changes, and every option: [channels, states and slots](configuration/slots.md), the [channel types](configuration/channels/index.md), the parts of a strip. |
| Reference | Every [command](reference/commands.md), the [hardware and its protocol](reference/hardware.md), the [voice chat bridge](reference/voice-chat-bridge.md). |
| Development | How it works inside ([Architecture](development/architecture/index.md)) and why ([Design documents](development/index.md)). |
