# Design: an interactive device test

Status: proposed (2026-11-18), not built yet. See TODO.md.

## Problem

`xtouch-daemon test` lights everything up once (every LCD in a color, the LEDs, rings and meters, the faders up and
down), resets the device and then only prints what happens on it: `strip 3: mute pressed`, `strip 3: encoder +1`.
The device stays dark meanwhile.

That tells whether the device sends, but not whether it shows what we send it, nor whether the drawing of the GUI
(the twin of the device, `simulator/device.py` and the window Device) shows what the device shows. Both are guesses
from the protocol and from looking at the device once; a defective device (touch sensors that don't work, an LED
that stays dark) is also only found by chance.

## Idea

After the sweep, the test doesn't go silent: every strip answers its own controls, so each output of the device is
reached by an input on the same strip, and every value of every output can be shown by hand. The log stays as it is,
with what the strip shows in answer after each input.

| Input on a strip | What the strip shows |
|---|---|
| Fader moved | The meter shows the position of the fader (0..`METER_MAX`, sent again while it is up, since the device lets a meter fall by itself). The LCD shows `fad 63%` for a moment. |
| Fader touched, let go | The LCD shows `touch` / `let go` for a moment; while touched, the top line is inverted in color (see "The LCD" below). |
| Rec, Solo, Mute, Select pressed | Its LED goes to the next state: off, on, flashing, off. The LCD shows `mute on`, `mute fl`, `mute off` for a moment. |
| Encoder turned | Steps the value the encoder edits (see below) up or down, wrapping around, and shows it on the LCD. |
| Encoder pushed | Switches what the encoder edits: the position of the ring, its mode, the color of the LCD. The LCD names it. |

### The encoder

A push switches between three things it edits, the turn steps through all of their values:

1. **ring**: the position, 0 (dark) and 1..`RING_MAX`, in the mode chosen.
2. **mode**: the 4 modes of the ring (`dot`, `boost_cut`, `wrap`, `spread`), each without and with the center LED:
   8 values. The position stays, so each mode shows how it lights that position.
3. **color**: the 8 backlight colors of the LCD (`BLACK` .. `WHITE`).

So every value the protocol can set on the ring and the LCD color is reached on every strip, and the drawing of the
GUI can be compared for each.

### The LCD

- Top line: the strip (`strip 3`) and, after a push of the encoder, what the encoder edits (`ring`, `mode`, `color`).
- Bottom line: the last input on that strip (`mute fl`, `enc +1`, `fad 63%`, `ring 7`, `cyan`), for
  `INPUT_SECONDS` (2 s), then back to what the encoder edits and its value.
- Every strip starts in its own color, as in the sweep, so the colors of the 8 strips can be compared at once.

### What stays

- The sweep at the start, unchanged.
- `--no-events` ends after the sweep, as now.
- The log of every input (`describe()`), and the messages the daemon doesn't use (`unknown message: ...`).
- Ctrl+C resets the device and ends.

## Comparing with the twin

The Surface already keeps a mirror of what it sent (`Surface.mirror`, a `SimulatedDevice`), which is what the GUI
draws for a daemon. The test runs on a Surface as well, so its mirror has the same state. Two ways to put the twin next
to the device:

- **The GUI shows the test** (preferred): the test serves the live socket like the daemon (a snapshot from the mirror;
  no configuration and no requests), so the window Device of a GUI that is open draws what the test sent.
  The device and its drawing side by side, input by input. Needs a part of the live server of the daemon without the
  rest of it.
- **The test runs on the virtual device**: `xtouch-daemon test --virtual-device`, with the GUI hosting the virtual
  device and Play as the hand. That tests the test and the twin against each other, not against the device, but it
  is cheap (`device_port()` already makes the port).

## Building it

- `hardware/selftest.py`: a `TestBench` that takes the events of the Surface (`on_event`) and keeps the state of each
  strip in a typed dataclass (LED states, what the encoder edits, ring position and mode, color, fader). A temporary text
  ends with a timer per strip, which the next input on that strip replaces; the old handle is cleared before anything
  awaits, so two quick inputs can't leave a timer running. A task sends the meters of raised faders again.
- `cli/daemon.py`: `test` unchanged in its options; maybe `--virtual-device` (see above).
- Tests: against the simulated device (`tests/support/simulator.py`, `MemoryPort`): an input as the device sends it,
  then what the mirror shows (LED states, ring, color, LCD texts, meter), and that a temporary text goes back.
- Docs: `reference/commands.md#test` (what each input does), `reference/hardware.md` (testing a device).

## Open questions

- The faders: should the test also move them on request (e.g. a double press of Select sends the fader to 0 %, 50 %,
  100 % in turn), to test the motors and touch sensors again after the sweep? A motor fader that is touched while
  it moves is a case the daemon has to handle, so it is worth seeing on the device.
- An inverted top line while the fader is touched needs an LCD mode the protocol module doesn't send yet (Behringer's
  color byte has bits for inverted lines); check on the device first, else drop it.
- The GUI showing the test needs a live server without a daemon: worth it for the first version, or a second step?
