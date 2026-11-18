# xtouch-daemon

xtouch-daemon turns a Behringer X-Touch Extender into a hardware mixer for PipeWire on Linux. Its motor faders, LED
meters and scribble strips control your devices and applications. A strip can also belong to Home Assistant instead,
for lights, speakers in other rooms or scenes.

![The GUI: the device as it is, the slots and the inspector of the slot picked](images/gui.png)

## Features

### Strips

- **Device strips** (`output`, `input`) control an output or an input, or whatever is the default. **Select** makes
  the device the default, and its LED shows which one is. See [Devices](configuration/channels/devices.md).
- **Several devices on one strip:** a list or a `*` wildcard (e.g. `bluez_output.*` for any Bluetooth headphones).
  The strip shows the one that is there, and Select switches between them.
- **Sound card profiles:** Rec switches the card between profiles, e.g. analog and digital output. The label of the
  active profile names the strip, and each profile can have its own volume range.
- **Application strips** (`apps`) control all streams of a group of applications at once, e.g. every browser. A
  stream that starts later gets the strip's volume. See [Applications](configuration/channels/applications.md).
- **Auto strips** (`auto`) pick up the next application that plays and has no strip of its own. They keep it for a
  few seconds after it stops, so it does not jump between strips from track to track. The encoder picks another
  application, a push pins it. Aliases give applications readable names.
- **Home Assistant strips** (`homeassistant`) turn a strip into entities for your automations over MQTT discovery: the
  motor fader, the encoder, the LCD lines and color, the LEDs, and events for every button press. See
  [Home Assistant](guides/home-assistant.md).
- **Empty strips** (`empty`) stay dark and do nothing.

### On every strip

- **Motor faders** glide to new values smoothly, follow changes made anywhere else, and stay still while your finger
  is on them. Only a touched fader changes a value.
- **Volume ranges:** the fader covers `min_volume` to `max_volume`, up to 200 % (amplified in software). See
  [Strips](configuration/channels/index.md#volume-range).
- **Scribble strips** show a label and the volume (or `muted`, `idle`, `off`) on a backlight in the strip's color. A
  strip whose device or applications are not there goes dark.
- **Mute** button with LED.
- **Encoder modes:** the encoder sets the balance, fine-tunes the volume, picks the application of an `auto`
  strip, or seeks and plays/pauses the media player of the applications. Its LED ring shows what it controls.
- **Home Assistant controls on audio strips:** the encoder (or the fader) becomes an entity in Home Assistant, e.g. to
  dim a light, while the other control keeps the volume. See [Encoders](configuration/strip/encoders.md).
- **Rec and Solo LEDs as indicators:** recording, playing, default or muted. See
  [LEDs](configuration/strip/leds.md).
- **LED meters** show the level of each strip, before or after its fader (`meter_point`), and light their red LED for
  half a second when the audio clips (a peak at full scale). They are passive: they never wake a device, never light your desktop's microphone indicator,
  and never switch Bluetooth headphones into headset mode.

### Around it

- **GUI editor** (`xtouch-daemon gui`): the eight strips as the device shows them right now, editing with errors next
  to the options, suggestions from the sound server, drag to reorder, undo, "Try on the device" that runs the unsaved
  changes on the device, and save-and-apply that keeps the comments of the file. See [GUI](guides/gui.md).
- **Command line tools:** a device self-test, lists of devices, profiles and applications, a configuration check. See
  [Commands](reference/commands.md).
- **Robust:** survives unplugging or switching off the device and restarts of the sound server and the MQTT broker,
  and shows everything again when they are back.
- **A proper service:** a systemd user service with readiness notification (`Type=notify`). `systemctl --user reload`
  applies a changed configuration without a restart, and the log goes to the journal with levels. Startup and
  shutdown sequences light the strips up and turn them dark: one after the other, all at once, like a curtain or
  behind a wave of light. When it stops, it leaves the
  surface dark.

## Requirements

- Linux with PipeWire and `pipewire-pulse` (or PulseAudio).
- `pw-record` (part of PipeWire) for the meters.
- Python 3.14.
- A Behringer X-Touch Extender in **MC** mode on **USB** (see [Getting started](getting-started/first-steps.md#set-up-the-device)).
- For Home Assistant strips: an MQTT broker that Home Assistant uses (e.g. the Mosquitto add-on).

## Where to go next

| Section | What it covers |
|---|---|
| [Getting started](getting-started/install.md) | Install, set up and test the device, write a first configuration, run the service; or try it [without a device](getting-started/without-a-device.md). |
| Guides | The [GUI](guides/gui.md), [Home Assistant](guides/home-assistant.md), [Mumble](guides/mumble.md), and [Troubleshooting](guides/troubleshooting.md). |
| [Configuration](configuration/index.md) | The file, applying changes, and every option: [channels, states and slots](configuration/slots.md), the [channel types](configuration/channels/index.md), the parts of a strip. |
| Reference | Every [command](reference/commands.md), the [hardware and its protocol](reference/hardware.md), the [voice chat bridge](reference/voice-chat-bridge.md). |
| Development | How it works inside ([Architecture](development/architecture/index.md)) and why ([Design documents](development/index.md)). |
