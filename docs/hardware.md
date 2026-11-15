# Hardware

The Behringer X-Touch Extender has 8 strips. Each has a 100 mm motorized, touch-sensitive fader, four buttons with
LEDs (Rec, Solo, Mute, Select), an encoder with a push button and an LED ring, an LED meter, and an LCD with two lines
of 7 characters and one of 8 backlight colors.

xtouch-daemon drives it over USB in its Mackie Control mode, so it acts as the "host" a DAW would be. The device needs
no driver: it is a USB class compliant MIDI device.

## Setting up the device

The extender has to be in **MC** mode on **USB**. Out of the box it may be set to the network interface: then it
shows `IP: 192.168.001.100 wait...` and ignores USB.

1. Switch it off.
2. Hold the **Select** button of strip 1 and switch it on: the setup menu opens.
3. Set **Mode** to `MC` and **Interface** to `USB` with the encoders.
4. Leave the menu (Select of strip 1 again, or switch it off and on).

Check it with `xtouch-daemon test`: every strip lights its LCD in a color, its LEDs, ring and meter, and moves its
fader. Afterwards the command echoes what you do on the device.

## Linux access

Linux lists the extender as a sound card (`/proc/asound/cards`: `XTouchExt ... X-Touch-Ext`) with the raw MIDI device
`/dev/snd/midiC<card>D0`. xtouch-daemon finds the card by its name (`[device] name`) and opens that device directly,
without ALSA sequencer or JACK.

The user needs read and write access to it. Desktop sessions give it to the logged-in user through the seat (logind).
Without a session, add the user to the `audio` group.

Only one program can have the device open. Stop the daemon before `xtouch-daemon test`, and close DAWs that use it.

## Motor faders

- **Touch:** while a finger is on a fader, its motor does not follow outside changes. When the fader is let go, it
  moves to the strip's current value, usually the one that was set last.
- **Only a touched fader sets a value:** a hand touches a fader before it moves it. A move without a touch comes from
  the device itself (e.g. its faders going down after it was switched on), so the fader goes back to its value. A
  fader whose touch sensor failed can't change the volume until it is repaired.
- **Smooth motion:** a fader glides to a new value instead of jumping there. It follows its target like a critically
  damped spring (no overshoot) that gets there in about 100 ms, starting from where it is, also from where a hand left
  it. The spring keeps its speed when the target moves on, so a volume dragged in another mixer, which arrives in small
  steps, becomes one even movement.
- **Arriving:** once a fader is there, its value is sent twice more (after 0.15 s and 0.4 s), in case the motor
  stopped short of it. Stopping the daemon waits for that.
- **Slow moves:** the big moves glide three times slower, and stay slow until the fader arrived: a fader that is put
  away because its strip goes dark (the daemon stops, an application ended, a reload), and the first move after a
  connect. After a fast move the motor stops a little short of the bottom; a slow one gets there. Tried on the device:
  neither sending the value again nor a nudge (a little up, then down again) did as well.
- **Startup and shutdown sequences:** after a connect the strips light up one after the other from the left, 80 ms
  apart, and their faders come up; when the daemon stops they go dark from the right and their faders go down.
- **Start:** the device can't tell where its faders are. It reports a position only while a finger moves a fader,
  not after a connect, not on the device query, not after a motor move. So after a connect a fader is assumed at the
  bottom, where the daemon leaves the faders when it stops, and glides from there. If it was moved while the daemon
  did not run, its first step jumps from where it really is.
- **Motor noise:** slight steps can be heard while a fader moves, more above about 70 %. They come from the device,
  not from the values sent: a perfectly even 14-bit ramp at 100 Hz sounds the same. The motor control works in small
  steps (the positions the device reports are multiples of 4, so 12 bits), and the slider has play on its rail: the
  belt tilts it one way going up and the other way going down, which clicks. Don't grease it: the touch sensing goes
  through the knob and slider.
- **Fast moves:** the device sends many positions per second. Only the latest one is set when the previous command
  finished, so a slow sound server does not build a queue.

## Protocol

The Mackie Control protocol; the extender is an MCU XT (model id `0x15`). Verified on the device (2026-11-15) unless
marked otherwise. `n` is the strip, 0..7.

### From the device

| Element | Message |
|---|---|
| Host query | `F0 00 00 66 15 01 <7 byte serial> <4 byte challenge> F7`, sent on its own after start. The device works without an answer. |
| Fader | Pitch bend on channel `n`: `En lsb msb`, 14 bits (`0x0000..0x3FFF`) |
| Fader touch | Note `0x68 + n`, velocity `7F` touched, `00` released |
| Buttons | Note on, velocity `7F` pressed, `00` released: Rec `0x00 + n`, Solo `0x08 + n`, Mute `0x10 + n`, Select `0x18 + n` |
| Encoder turn | CC `0x10 + n`: `01..3F` clockwise, `41..7F` counter-clockwise (the low 6 bits are the steps) |
| Encoder push | Note `0x20 + n` |

### To the device

| Element | Message |
|---|---|
| Fader motor | Pitch bend, like the fader position |
| Button LEDs | Note of the button, velocity `7F` on, `01` flashing, `00` off |
| LED ring | CC `0x30 + n`, value `0x40` (center LED) \| mode `<< 4` (0 dot, 1 boost/cut, 2 wrap, 3 spread) \| position 0 (off) or 1..11 |
| Meter | Channel pressure `D0`, value `n << 4 \| level`, level 0..12. The device lets it fall by itself, so it must be sent again to hold a level. |
| LCD text | `F0 00 00 66 15 12 <offset> <ASCII> F7`, offset `line * 56 + n * 7` |
| LCD colors | `F0 00 00 66 15 72 <8 colors> F7` (a Behringer extension, works in MC mode): 0 black, 1 red, 2 green, 3 yellow, 4 blue, 5 magenta, 6 cyan, 7 white |

The codec is in [`protocol.py`](../src/xtouch_daemon/protocol.py): pure functions that decode the device's messages
into events and build the messages that drive it.
