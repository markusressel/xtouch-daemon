# xtouch-daemon: Guide for AI Agents

Drives a Behringer X-Touch Extender (Mackie Control over USB MIDI) as a hardware mixer for PipeWire. Python 3.14 (haad-mqtt-autodiscovery, a path dependency in `../haad-mqtt-autodiscovery`, requires it),
uv, src layout. Start with [docs/architecture.md](docs/architecture.md).

## Layout

| Path | Purpose |
|---|---|
| `src/xtouch_daemon/protocol.py` | Mackie Control codec (pure functions). |
| `src/xtouch_daemon/midi.py` | Raw MIDI device (`/dev/snd/midiC*D0`). |
| `src/xtouch_daemon/surface.py` | `Surface`/`Strip`: device state, reconnects, motor glide. |
| `src/xtouch_daemon/audio/` | `AudioState` model, `AudioBackend` protocol, `PulseBackend`, `pw-record` meters. |
| `src/xtouch_daemon/strips/` | Strip controllers (`output`/`input`, `apps`, `auto`, `homeassistant`, `empty`). |
| `src/xtouch_daemon/mqtt.py` | `MqttBridge`: the MQTT connection for Home Assistant (discovery, retained states, availability). |
| `src/xtouch_daemon/mixer.py` | Feeds states and events to the controllers. |
| `src/xtouch_daemon/launch.py` | Starting the application of a strip's `launch` (Select), detached from the daemon. Tests use `FakeLauncher`; `conftest.no_launches` makes a real start fail. |
| `src/xtouch_daemon/daemon.py` | Lifecycle: signals, reload, shutdown, sd_notify. |
| `src/xtouch_daemon/instance.py`, `live.py` | The running daemon for the GUI: its runtime file, and the live view of the device over a Unix socket. |
| `src/xtouch_daemon/config.py`, `config.example.toml` | pydantic configuration and the example file. |
| `src/xtouch_daemon/cli.py`, `selftest.py`, `systemd.py` | CLI, device self-test, systemd integration (incl. controlling the user service). |
| `src/xtouch_daemon/voip/`, `layouts.py` | VoIP providers (`bridge` socket for plugins, `demo`), layout switching and rules. |
| `src/xtouch_daemon/mumble.py`, `integrations/mumble/` | The Mumble plugin (C, CMake, vendored `MumblePlugin.h`) and finding, building and installing its bundle. `test/fake_mumble.c` is the host `tests/test_mumble_plugin.py` loads it into. |
| `src/xtouch_daemon/gui/` | Optional `xtouch-daemon gui` (extra `gui`, PyQt6): `domain/` is toolkit-free and fully tested, `qt/` the widgets. Forms come from the pydantic models, so new options need no GUI code. |
| `tests/` | One test module per source module; fakes in `tests/conftest.py`, an in-memory MQTT broker in `tests/fake_mqtt.py`. |
| `docs/`, `zensical.toml` | The documentation site (Zensical, published to GitHub Pages by `.github/workflows/docs.yml`): `index.md`, `getting-started.md`, `configuration/*.md` (one page per topic), `home-assistant.md`, `gui.md`, `commands.md`, `troubleshooting.md`, `hardware.md`, `architecture.md`. Build it with `just docs`. |
| `packaging/` | Release tarballs (`build-release.sh`), the pinned commit of haad-mqtt-autodiscovery, the GUI's `.desktop` file, the AUR packages (`aur/`, `aur/publish.sh`). See [RELEASING.md](RELEASING.md). |

## Commands

```shell
uv sync
just test            # uv run pytest -n auto (in parallel); one test: uv run pytest tests/test_x.py -k name
just coverage        # in parallel too, fails below 90 %
just lint            # ruff check + ruff format --check + codespell
just typecheck       # pyright
just check           # all of the above, like CI
just docs            # builds the documentation site (strict: broken links fail)
```

## Rules

- Update the docs (README, `docs/`, `config.example.toml`, `CHANGELOG.md`) with every behaviour change. Verify every
  documented command and option against `cli.py` and `config.py`. Links between pages are relative (they work on
  GitHub and on the site); links to files outside `docs/` are absolute GitHub URLs. `just docs` must pass.
- Every behaviour change needs tests. Coverage stays ≥ 90 % (lines and branches).
- The C plugin is tested end to end (built with CMake, loaded into `fake_mumble`, against `BridgeProvider`); those
  tests are skipped without cmake and a C compiler. Never test against a real Mumble in the tests.
- No hardware and no PipeWire/PulseAudio in unit tests: use a fake `AudioBackend`, a fake pulsectl connection, a
  recording surface, a FIFO or pty for MIDI, a fake `pw-record` script.
- Tests run in parallel (pytest-xdist) and must not depend on each other or on the order they run in.
- Asyncio tests run in virtual time (looptime, `--looptime` in `addopts`): sleeps and timeouts take no real time, and
  `loop.time()` moves only with them. Measure time in async code with `loop.time()` or an injected clock, never with
  `time.monotonic()`, and assert durations exactly instead of polling. Tests with real processes, devices or buses
  (their answers come in real time) are marked `pytest.mark.looptime(False)`.
- A test leaves nothing behind: `conftest.no_leaks` fails it for a process it did not wait for (cancel and await the
  tasks that own processes, kill and wait for the processes). Tests see nothing of the machine they run on:
  `conftest.no_host` fails a test that touches the processes, sound devices, the user's files, the session bus or the
  runtime directory of the machine; a test that does so on purpose is marked `host`.
- Type hints everywhere; `ruff` and `pyright` must pass.
- Git: commit, but never push. The user pushes.
