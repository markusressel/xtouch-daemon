# Design: a simulated device

Status: built (2026-11-17), extended 2026-11-18 (see [Decisions](#decisions)).

## Why

The X-Touch Extender used for development was defective (the touch sensors of faders 1 and 4 failed) and went back.
Without a device nothing above the protocol can be tried outside the tests: no slots on strips, no fader under a
finger while a slot changes, no LEDs and texts to look at. The protocol and the behavior of the device are known well
(see [Hardware](../../reference/hardware.md), verified on the device on 2026-11-15), so a simulated device can stand in for it:
for development, for the GUI, and for tests that run the real `Surface` end to end.

The model is also how the GUI sees the device (decided 2026-11-17): the daemon keeps one as a mirror of the device it
drives, and the GUI shows the mirror. One model of the device, then, for the virtual device, the GUI and the tests.

## Goals

- The daemon talks to the simulated device with the same bytes as to the real one. Everything above the transport
  (`Surface`, its touch grace, touchless faders, the glide of the motors, the startup sequence, reconnects) runs
  unchanged, so it gets tried too.
- The simulated device behaves like the real one where [Hardware](../../reference/hardware.md) says how, including faults: a
  touch sensor that fails (like the returned unit), the device switched off and on (faders move by themselves), unplugged.
- One model of the device, without IO and without Qt, behind its frontends: the mirror in the daemon (what the GUI
  shows), a socket server for the daemon, the GUI's drawing to use it, and a test fixture.
- No root, no kernel modules: it has to work in CI and in a user session.

Not a goal: proving timing-sensitive motor behavior (slow moves, the stop short of the bottom, motor noise). The
simulator models the motor simply; those need the real device.

## Rejected: a virtual ALSA MIDI device

The kernel's `snd-virmidi` makes raw MIDI devices that `Surface` would find in `/proc/asound/cards` without any
change. But it needs `modprobe` (root), its other end is the ALSA sequencer (a second API for the simulator), and it
doesn't work in CI. A transport of our own is simpler and testable.

## Design

### 1. A transport seam in `Surface`

- `hardware/transport.py`: a `Transport` protocol with what `Surface` uses of `RawMidi` (`write`, `drain`, `close`,
  `is_open`; data and the end come through the callbacks `on_data` and `on_closed`). `RawMidi` is one.
- A `Port` finds and opens a transport, `LookupError` when there is no device:
  - `AlsaPort(device_name, proc_asound_cards, dev_snd)`: finds the card in `/proc/asound/cards` and opens
    `/dev/snd/midiC<card>D0` as `RawMidi`.
  - `SocketPort(path)`: connects to the simulator's Unix socket. No simulator running is "not connected", so
    `Surface.run()` waits and connects when it starts, and a closed simulator is an unplugged device: the reconnect
    path gets used.
- `Surface(port=...)`; the daemon picks the port from the configuration: `[device] virtual = true` (or
  `xtouch-daemon run --virtual-device`, which wins) uses `SocketPort(instance.virtual_device_socket_file())`, next to the
  other runtime files (`$XDG_RUNTIME_DIR/xtouch-daemon/`).
- The log says which: "Connected to the simulated X-Touch-Ext at ...".

### 2. The messages to the device, decoded

`hardware/protocol.py` builds the messages to the device (`fader`, `led`, `ring`, `meter`, `lcd_text`,
`lcd_colors`) and decodes those from it. The simulator needs the other direction:

- `decode_host(message) -> HostEvent | None` with `MotorMoved(strip, value)`, `LedSet(strip, button, Led)`,
  `RingSet(strip, position, mode, center)`, `MeterSet(strip, level)`, `LcdText(offset, text)`,
  `LcdColors(colors)`.
- And the encoders for what the device sends: `fader_moved`, `fader_touched`, `button`, `encoder_turned`,
  `encoder_pressed`, `host_query`.
- Round-trip tests: every encoder against its decoder, both directions, over the full value ranges.

### 3. The model: `simulator/device.py`

`SimulatedDevice`, pure (no IO, no asyncio, no Qt): it takes bytes from the host and the time, and gives bytes for
the host. Time comes in as an argument (`now`), so tests and frontends drive it.

State per strip:

- LCD: two lines of 7 characters (written by offset into the 2 x 56 characters, as the device does), and the color.
- The LEDs of Rec, Solo, Mute and Select: off, on, flashing.
- The ring: position 0..11, mode, center LED.
- The meter: the level and when it was set; it falls by itself. The rate of the fall is not measured: about one
  level per 150 ms, marked as an assumption (see "Fidelity").
- The fader: where it is (14 bits, but positions in multiples of 4 as the device reports them), the motor's target,
  touched or not. The motor goes to the target at a fixed speed (about 100 ms over the whole range), not while
  touched; a motor move sends nothing back (the real device doesn't either).
- The encoder: pressed or not.

Input (what a hand does), each giving the bytes the device sends:

- `touch(strip, touched)`, `move(strip, fraction)`: a move while not touched follows the real device: with
  `touch_delay` (default 0.07 s) the touch comes after the first moves, as with a quick hand.
- `press(strip, button, pressed)`, `turn(strip, steps)`, `push(strip, pressed)`.

Faults and events:

- `broken_touch: set[int]`: these faders never report a touch (the returned unit: `{0, 3}`).
- `power_cycle()`: sends the host query, then the faders go down by themselves (moves without a touch), as after
  switching the device on; texts, colors and LEDs are gone until the host sends them again.
- The host query on connect: `F0 00 00 66 15 01 <serial> <challenge> F7` with a made-up serial.
- Unplugging is the frontends' business (they close the connection).

A `changed` callback (or a version counter) tells frontends to repaint.

### 4. The mirror: what the GUI shows

The `Surface` keeps a `SimulatedDevice` as the mirror of the device: every byte it sends goes into it (also while
the device is away: then it is what the device will show once it is there), and what the device sends goes in too
(`observe()`: fader moves, touches, encoder pushes). The device's query after switching on changes nothing: the
`Surface` shows everything again on each connect, and after one the mirror doesn't know where the faders are until
the motor moved them or the device reported a move (`forget_faders()`). The
live view's strips are the mirror's state (`strip_states()`), so the GUI shows what reached the device, banners and
flashes included, with the motor and the meters moving as the model moves them. The `Surface` keeps its own record of
what each strip shows only where it needs it to send (the strips' values and looks).

What the mirror can't know: what the device does without saying (a motor that stopped short, where the faders are
after a connect). It shows what was sent and what the device reported.

### 5. The virtual device and its frontends

`simulator/server.py`: a Unix socket server at `instance.virtual_device_socket_file()` with one `SimulatedDevice`.
One client at a time (the daemon); a second one is refused, like a device another program has open. A tick (every
10 ms) moves the motors and lets the meters fall. The same device stays when the daemon disconnects and connects
again, so a daemon restart sees the faders where they were, as on the real device.

- **CLI**: `xtouch-daemon virtual-device` runs the server headless, logs what the host sets at debug level, and
  takes a few options (`--broken-touch 1,4`). (Not `simulate`: that one simulates slots.)
- **GUI**: the GUI can host the server itself (a `QLocalServer` around the same `SimulatedDevice`). Then its drawing
  of the device takes the mouse, sent to the hosted device as a hand:
  - a fader: press = touch, drag = moves, release = let go; Alt-drag moves it without a touch;
  - the buttons: click (press and release), held while the mouse is down;
  - the encoder: the wheel or a drag on the knob turns it (up or right is clockwise), a click pushes it, holding
    holds it down, and holding on an LED of the ring turns it until the ring lights that LED
    (`gui/quick/device/encoder_hand.py`);
  - a toolbar: plug in / unplug, switch off and on, broken touch per fader.

  What it paints still comes from the live view (the daemon's mirror), which is the hosted device's state once it got
  there; the GUI doesn't paint two models. While the daemon waits for a device that isn't connected, the pill "X-Touch-Ext
  not connected" offers "Open the virtual device"; nothing starts without a click.
- **Tests**: a fixture that connects a real `Surface` to a `SimulatedDevice` through an in-memory transport (no
  socket), with the loop's clock (`looptime`). New end-to-end tests: touch grace, touchless faders, the glide arriving,
  the startup sequence, a power cycle, a reconnect, a slot change under a finger. `RecordingSurface` stays for the
  tests that only look at what was sent.

### 6. Fidelity

What the simulator does is either verified on the device (it says so in [Hardware](../../reference/hardware.md)) or an
assumption; the assumptions are listed in the module's docstring and in the docs: the speed of the motor, the fall
of the meters, the delay of the touch, the moves after switching on. [The interactive test](interactive-test.md) is meant to replace
assumptions with comparisons on the device.

## Decisions

- (2026-11-17) The CLI command is `xtouch-daemon virtual-device`, the option `[device] virtual = true`, and
  `xtouch-daemon run --virtual-device` overrides it.
- (2026-11-17) The GUI offers the virtual device but doesn't start it: while the daemon waits for a device that isn't connected,
  the pill "X-Touch-Ext not connected" has "Open the virtual device". Nothing starts without a click.
- (2026-11-18) The mouse on the drawing is a hand only in Play; Select (the default) picks and moves slots. Play also
  works on the device of a running daemon through the live view (`live.Play`, `Surface.play()`), so the GUI is a
  remote control for the real device too. While no daemon runs, "Try without a device" starts one with the virtual
  device on the file and hosts it: a demo for people without the device. It is the one thing the GUI starts by
  itself, and only on that click; it ends with the window.
