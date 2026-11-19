# Hardware and protocol

The Behringer X-Touch Extender has 8 strips. Each has a 100 mm motorized, touch-sensitive fader, four buttons with
LEDs (Rec, Solo, Mute, Select), an [encoder](../configuration/strip/encoders.md) with a push button and an [LED](../configuration/strip/leds.md) ring, an LED meter, and an LCD with two lines
of 7 characters and one of 8 backlight colors.

The meter has 8 LEDs: seven for the level (green, then orange) and a red clip LED at the top. Mackie Control sets it
in 14 levels, about two per LED (only the 14th lights the clip LED), and the device lets it fall by itself. What the
levels mean on an audio strip, and whether they are taken before or after the fader, is in
[Meters](../configuration/channels/index.md#meters).

![The eight strips as the GUI draws them, from the top: encoder and LED ring, LCD, meter and buttons, fader](../images/device.png)

xtouch-daemon drives it over USB in its Mackie Control mode, so it acts as the "host" a DAW would be. The device needs
no driver: it is a USB class compliant MIDI device.

[First steps](../getting-started/first-steps.md#set-up-the-device) sets the device up (MC mode on USB) and
tests it.

## Linux access

Linux lists the extender as a sound card (`/proc/asound/cards`: `XTouchExt ... X-Touch-Ext`) with the raw MIDI device
`/dev/snd/midiC<card>D0`. xtouch-daemon finds the card by its name (`[device] name`) and opens that device directly,
without ALSA sequencer or JACK.

The user needs read and write access to it. Desktop sessions give it to the logged-in user through the seat (logind).
Without a session, add the user to the `audio` group.

Only one program can have the device open: close DAWs that use it. [`xtouch-daemon test`](commands.md#test) asks a
running daemon to test the device.

To check a device: [`xtouch-daemon test`](commands.md#test), or "Test the device" in the [GUI](../guides/gui.md#test-the-device),
which draws the device next to it. Every strip answers its controls, so each LED, the ring in each mode, the LCD
colors, the meter, the motor and the touch sensor of every fader can be checked by hand, and compared with the
drawing. The modes with `+c` set the `center` bit of the ring's message, which lights the two LEDs at the ends of
the ring (see the table below).

## Motor faders

- **Touch:** while a finger is on a fader, its motor does not follow outside changes. When the fader is let go, it
  moves to the strip's current value, usually the one that was set last.
- **Only a touched fader sets a value:** the device reports a touch about 50-100 ms after the first moves of a quick
  hand. A move without a touch waits for one for 0.3 s with the motor still: with a touch it was the hand and counts,
  without one it was the device itself (e.g. its faders going down after it was switched on), and the fader goes back
  to its value. A fader whose touch sensor failed can't change the volume until it is repaired, or until it is one of
  the [`touchless_faders`](../configuration/behavior.md#faders-without-a-touch-sensor). With `touch_required = false`,
  every move of every fader counts.
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
- **Startup and shutdown sequences:** after a connect the strips light up and their faders come up; when the daemon
  stops they go dark and their faders go down. By default one after the other, from the left and from the right;
  `[device] startup` and `shutdown` choose others, see
  [Startup and shutdown sequences](../configuration/behavior.md#startup-and-shutdown-sequences). The device can't blink
  a ring and has no brightness levels, so the light effects are steps of on and off.
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

## The virtual device

`xtouch-daemon virtual-device` and the GUI simulate the device (`simulator/device.py`), byte for byte, on a Unix
socket in the runtime directory instead of `/dev/snd`. The daemon keeps the same model as a mirror of the real
device, which is what the GUI draws. What it does like the device, as described on this page: the messages of
[Protocol](#protocol) both ways, the LCD as two lines of characters across the strips, a touch on a fader, positions
reported in steps of 4, the motor that moves only when the host sets a value or a finger lets go, never under a
finger, a fader whose touch sensor failed (no touch reported), and switching it off and on (its query, everything
dark, the faders going down by themselves and reporting it).

What is assumed: how fast the motor goes (0.1 s over the whole travel), how fast a meter falls (one level per
0.15 s), and when the touch of a quick hand comes (70 ms after its first move).

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
| LED ring | CC `0x30 + n`, value `0x40` (center LED) \| mode `<< 4` (0 dot, 1 boost/cut, 2 wrap, 3 spread) \| position 0 (off) or 1..11. The ring has 13 LEDs: the positions light the middle 11, and Mackie Control's center LED (`0x40`) lights the two at the ends, together. |
| Meter | Channel pressure `D0`, value `n << 4 \| level`, level 0..14. One more of the 8 LEDs every two levels (1–2 light one, 9–10 five), 11 lights six, 12–13 seven, 14 all eight with the red one at the top. 15 lights none. The device lets every level fall by itself (14 too: there is no overload LED it holds, unlike Mackie Control's `0x0E`), so it must be sent again to hold a level. |
| LCD text | `F0 00 00 66 15 12 <offset> <ASCII> F7`, offset `line * 56 + n * 7` |
| LCD colors | `F0 00 00 66 15 72 <8 colors> F7` (a Behringer extension, works in MC mode): 0 black, 1 red, 2 green, 3 yellow, 4 blue, 5 magenta, 6 cyan, 7 white |

The codec is in
[`hardware/protocol.py`](https://github.com/markusressel/xtouch-daemon/blob/main/src/xtouch_daemon/hardware/protocol.py): pure
functions that decode the device's messages into events and build the messages that drive it.

Messages the daemon does not use are not lost: `xtouch-daemon test` prints them (`unknown message: ...`), and the
daemon logs them at debug level (`xtouch-daemon run -l debug`). They show what a device sends that differs from the
table above, e.g. a touch that is not the usual note.

See [Troubleshooting](../guides/troubleshooting.md) for problems with the device.
