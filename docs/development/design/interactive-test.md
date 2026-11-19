# Design: an interactive device test

Status: built (2026-11-19). Differences from the design below: the top line of the LCD always names the strip, the
bottom line shows what the encoder edits (`ring 6`, `dot+c`, `cyan`, `fad 60%`) or, for 2 s, the last input; a turn
shows the new value rather than `enc +1`. The command with a running daemon doesn't print the inputs, the daemon's log
has them. The center bit lights the two LEDs at the ends of the ring, as measured before (`reference/hardware.md`).

## Problem

`xtouch-daemon test` lights everything up once (every LCD in a color, the LEDs, rings and meters, the faders up and
down), resets the device and then only prints what happens on it: `strip 3: mute pressed`, `strip 3: encoder +1`.
The device stays dark meanwhile.

That tells whether the device sends, but not whether it shows what we send it, nor whether the drawing of the GUI
(the twin of the device, `simulator/device.py` and the window Device) shows what the device shows. Both are guesses
from the protocol and from looking at the device once; a defective device (touch sensors that don't work, an LED
that stays dark) is also only found by chance. And the test needs the daemon stopped, so the GUI can't draw it.

## Decisions (2026-11-18)

- It is `xtouch-daemon test`, extended: the same sweep, then the interactive part below instead of the silence. One
  test (`hardware/selftest.py`), started in two ways.
- The daemon can run it: the GUI starts and ends it with a button (and the command asks a running daemon), the
  daemon drives the device as always, and the GUI draws it as always (the live view of the mirror of the Surface). So
  the device and its twin are side by side, input by input, without stopping anything. Without a daemon,
  `xtouch-daemon test` opens the device itself, as now.
- The faders move on request too (the encoder edits them, see below).
- No inverted LCD lines: tried on the device, it doesn't do them.

## Idea

After the sweep, the test doesn't go silent: every strip answers its own controls, so each output of the device is
reached by an input on the same strip, and every value of every output can be shown by hand. The log stays as it is,
with what the strip shows in answer after each input.

| Input on a strip | What the strip shows |
|---|---|
| Fader moved | The meter shows the position of the fader (0..`METER_MAX`, sent again while it is up, since the device lets a meter fall by itself). The LCD shows `fad 63%` for a moment. |
| Fader touched, let go | The LCD shows `touch` / `let go` for a moment. |
| Rec, Solo, Mute, Select pressed | Its LED goes to the next state: off, on, flashing, off. The LCD shows `mute on`, `mute fl`, `mute off` for a moment. |
| Encoder turned | Steps the value the encoder edits (see below) up or down, wrapping around, and shows it on the LCD. |
| Encoder pushed | Switches what the encoder edits: the position of the ring, its mode, the color of the LCD. The LCD names it. |

### The encoder

A push switches between four things it edits, the turn steps through all of their values:

1. **ring**: the position, 0 (dark) and 1..`RING_MAX`, in the mode chosen.
2. **mode**: the 4 modes of the ring (`dot`, `boost_cut`, `wrap`, `spread`), each without and with the center LED:
   8 values. The position stays, so each mode shows how it lights that position.
3. **color**: the 8 backlight colors of the LCD (`BLACK` .. `WHITE`).
4. **fader**: the motor moves the fader to 0 %, 10 %, ... 100 %, a step a notch, to test the motor and, with a hand on
   it while it moves, the touch sensor. The meter follows, as for a fader moved by hand.

So every value the protocol can set on the ring, the LCD color and the fader is reached on every strip, and the
drawing of the GUI can be compared for each.

### The LCD

- Top line: the strip (`strip 3`) and, after a push of the encoder, what the encoder edits (`ring`, `mode`, `color`,
  `fader`).
- Bottom line: the last input on that strip (`mute fl`, `enc +1`, `fad 63%`, `ring 7`, `cyan`), for
  `INPUT_SECONDS` (2 s), then back to what the encoder edits and its value.
- Every strip starts in its own color, as in the sweep, so the colors of the 8 strips can be compared at once.

### What stays

- The sweep at the start, unchanged, also when the daemon runs the test.
- `--no-events` ends after the sweep, as now.
- The log of every input (`describe()`), and the messages the daemon doesn't use (`unknown message: ...`).
- Ctrl+C resets the device and ends.

## The daemon runs the test

- **Requests** (`live/messages.py`), as for the preview: `StartTest`, `KeepTest` (the GUI sends it while the mode
  runs) and `EndTest`; the snapshot says `test: bool`. Only a GUI of the same user (`owned`), as for Play and Try.
- **While it runs**, the Desk gives the events of the device to the test bench instead of the slots; the slots,
  states and Home Assistant go on as usual (the entities still tell what the slots would show), but nothing of theirs
  reaches the device. A control of Home Assistant that would act on the device waits.
- **It ends** with `EndTest`, when the connection of its GUI closes, after `TEST_TIMEOUT` without a request (like
  `PREVIEW_TIMEOUT`), and when the device goes away or is switched (`Surface.use`). Then the daemon draws everything
  of the slots again, as after a preview or a device that came back.
- **A preview and the test** don't run at the same time: starting one ends the other.
- **The GUI**: a "Test the device" button next to Play and Preview, checked while the mode runs, with a bar
  that says what each control does (the table above). Play works during the test: a click on the drawing is an input
  the test bench answers, the same as one on the device; so does the virtual device the GUI hosts.
- **The command**: `xtouch-daemon test` with a daemon running asks the daemon for the mode (and ends it with Ctrl+C)
  instead of failing because the device is taken; without a daemon it opens the device itself, as now, and the GUI
  can't draw it.

## Building it

- `hardware/selftest.py`: `run_selftest` grows the interactive part, a `TestBench` on a Surface, used by the command
  and by the daemon (the sweep too). It takes the events of
  the device and keeps the state of each strip in a typed dataclass (LED states, what the encoder edits, ring position
  and mode, color, fader). A temporary text ends with a timer per strip, which the next input on that strip replaces;
  the old handle is cleared before anything awaits, so two quick inputs can't leave a timer running. A task sends the
  meters of raised faders again.
- `runtime/daemon.py`: the mode (start, keep, end, timeout), the Desk handing over to the bench and back, drawing the
  slots again at the end.
- `live/`: the requests and `Snapshot.test`; `gui/qt/window/device_view.py`: the button and the bar.
- `cli/daemon.py`: `test` asks a running daemon (`system.instance`) first.
- Tests: the bench against the simulated device (`tests/support/simulator.py`, `MemoryPort`): an input as the device
  sends it, then what the mirror shows (LED states, ring, color, fader, LCD texts, meter), and that a temporary text
  goes back; the mode of the daemon (start, the slots not reaching the device, the ends, drawing again); the GUI's
  button and bar.
- Docs: `guides/gui.md` (the button), `reference/commands.md#test` (what each input does, a running daemon),
  `reference/hardware.md` (testing a device).
