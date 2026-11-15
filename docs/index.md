# xtouch-daemon

xtouch-daemon turns a Behringer X-Touch Extender into a hardware mixer for PipeWire on Linux. Its motor faders, LED
meters and scribble strips control your devices and applications. A strip can also belong to Home Assistant instead,
for lights, speakers in other rooms or scenes.

```
 ┌Speaker┐┌ Buds  ┐┌  Mic  ┐┌BudsMic┐┌Browser┐┌ VoIP  ┐┌ Games ┐┌Spotify┐
 │  46%  ││  44%  ││  80%  ││  off  ││  60%  ││ idle  ││ idle  ││  72%  │
 └───────┘└───────┘└───────┘└───────┘└───────┘└───────┘└───────┘└───────┘
   output   output   input    input    apps     apps     apps     auto
```

## Features

### Strips

- **Device strips** (`output`, `input`) control an output or an input, or whatever is the default. **Select** makes
  the device the default, and its LED shows which one is. See [Devices](configuration/devices.md).
- **Several devices on one strip:** a list or a `*` wildcard (e.g. `bluez_output.*` for any Bluetooth headphones).
  The strip shows the one that is there, and Select switches between them.
- **Sound card profiles:** Rec switches the card between profiles, e.g. analog and digital output. The label of the
  active profile names the strip, and each profile can have its own volume range.
- **Application strips** (`apps`) control all streams of a group of applications at once, e.g. every browser. A
  stream that starts later gets the strip's volume. See [Applications](configuration/applications.md).
- **Auto strips** (`auto`) pick up the next application that plays and has no strip of its own. They keep it for a
  few seconds after it stops, so it does not jump between strips from track to track. The encoder picks another
  application, a push pins it. Aliases give applications readable names.
- **Home Assistant strips** (`homeassistant`) turn a strip into entities for your automations over MQTT discovery: the
  motor fader, the encoder, the LCD lines and color, the LEDs, and events for every button press. See
  [Home Assistant](home-assistant.md).
- **Empty strips** (`empty`) stay dark and do nothing.

### On every strip

- **Motor faders** glide to new values smoothly, follow changes made anywhere else, and stay still while your finger
  is on them. Only a touched fader changes a value.
- **Volume ranges:** the fader covers `min_volume` to `max_volume`, up to 200 % (amplified in software). See
  [Strips](configuration/strips.md#volume-range).
- **Scribble strips** show a label and the volume (or `muted`, `idle`, `off`) on a backlight in the strip's color. A
  strip whose device or applications are not there goes dark.
- **Mute** button with LED.
- **Encoder modes:** the encoder sets the balance, fine-tunes the volume, picks the application of an `auto`
  strip, or seeks and plays/pauses the media player of the applications. Its LED ring shows what it controls.
- **Home Assistant controls on audio strips:** the encoder (or the fader) becomes an entity in Home Assistant, e.g. to
  dim a light, while the other control keeps the volume. See [Encoders](configuration/encoders.md).
- **Rec and Solo LEDs as indicators:** recording, playing, default or muted. See
  [LEDs](configuration/indicators.md).
- **LED meters** show the level of each strip. They are passive: they never wake a device, never light your desktop's
  microphone indicator, and never switch Bluetooth headphones into headset mode.

### Around it

- **GUI editor** (`xtouch-daemon gui`): the eight strips as the device shows them right now, editing with errors next
  to the options, suggestions from the sound server, drag to reorder, undo, and save-and-apply that keeps the comments
  of the file. See [GUI](gui.md).
- **Command line tools:** a device self-test, lists of devices, profiles and applications, a configuration check. See
  [Commands](commands.md).
- **Robust:** survives unplugging or switching off the device and restarts of the sound server and the MQTT broker,
  and shows everything again when they are back.
- **A proper service:** a systemd user service with readiness notification (`Type=notify`). `systemctl --user reload`
  applies a changed configuration without a restart, and the log goes to the journal with levels. Startup and
  shutdown sequences light the strips from the left and turn them dark from the right. When it stops, it leaves the
  surface dark.

## Requirements

- Linux with PipeWire and `pipewire-pulse` (or PulseAudio).
- `pw-record` (part of PipeWire) for the meters.
- Python 3.14.
- A Behringer X-Touch Extender in **MC** mode on **USB** (see [Getting started](getting-started.md#set-up-the-device)).
- For Home Assistant strips: an MQTT broker that Home Assistant uses (e.g. the Mosquitto add-on).

## Where to go next

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | Installation, device setup, the self-test, the first configuration, the service. |
| [Configuration](configuration/index.md) | The file, applying changes, and every option. |
| [GUI](gui.md) | The configuration editor. |
| [Home Assistant](home-assistant.md) | `homeassistant` strips, `[mqtt]`, automations. |
| [Commands](commands.md) | Every command of `xtouch-daemon`. |
| [Troubleshooting](troubleshooting.md) | Common problems and their fixes. |
| [Hardware](hardware.md) | The device, its motor faders and the Mackie Control protocol. |
| [Architecture](architecture.md) | How the daemon works inside, for developers. |
