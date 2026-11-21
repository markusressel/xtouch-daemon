# Testing

The tests run without hardware and without a sound server. `just test` runs them, `just coverage` fails below 93 %
line and branch coverage, or below 98 % without the Qt widgets (`gui/qt`).

## What stands in for what

| Part | Tested against |
|---|---|
| The protocol codec, the MIDI parser | Captured messages. |
| The raw MIDI device | A FIFO. |
| The `Surface` | A recording `send`, and end to end the `SimulatedDevice` in memory (`tests/support/simulator.py`, on the fake clock of the test) and over its socket. |
| The strips, the mixer, the daemon | A fake `AudioBackend`. |
| `PulseBackend` | A fake pulsectl connection. |
| The meters | A fake `pw-record` script. |
| The MQTT bridge, `homeassistant` strips | An in-memory broker (`tests/support/mqtt.py`): retained messages, subscriptions, last wills, lost connections. |
| The live view | A real Unix socket in a short temporary directory: clients that read, that don't read and that go away; requests of the user, of other users and too long ones; the live preview through the daemon. |
| The GUI's live preview | A fake live view (a `QLocalServer`) that answers like the daemon. |
| The Mumble plugin | Built with CMake and loaded into a fake Mumble (`integrations/mumble/test/fake_mumble.c`) that calls its callbacks as a script says, against a real `BridgeProvider`. Skipped without cmake and a C compiler. |
| The TeamSpeak plugin | The same with a fake TeamSpeak (`integrations/teamspeak/test/fake_teamspeak.c`), which aborts on a call into TeamSpeak from a callback. Skipped without cmake and a C compiler, or without TeamSpeak's plugin SDK, which the first build downloads. |
| The GUI | The domain with files in a temporary directory and a fake `systemctl`; the widgets with pytest-qt on the offscreen platform, a fake sound server, and dialogs the tests answer. |

The resolver and the state engine are pure, so each rule of [channels, states and slots](../design/slots/index.md)
has unit tests (`tests/slots/`), and one keeps the table of [its example](../design/slots/index.md#an-example) in line
with the file.

## Where things go

- The tests mirror the packages of the source (`tests/config/`, `tests/strips/`, `tests/gui/qt/`, ...).
- Fixtures are in the `conftest.py` files: `tests/conftest.py` has the guards every test gets (no processes left
  behind, nothing of the machine touched, no programs started) and the common fakes; the packages have their own
  (e.g. the window in `tests/gui/qt/conftest.py`).
- What tests import, fakes and helpers, is in `tests/support/`, never in a `conftest.py` or another test module.
