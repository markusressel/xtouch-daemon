# xtouch-daemon: Guide for AI Agents

Drives a Behringer X-Touch Extender (Mackie Control over USB MIDI) as a hardware mixer for PipeWire. Python 3.14 (haad-mqtt-autodiscovery, a path dependency in `../haad-mqtt-autodiscovery`, requires it),
uv, src layout. Start with [docs/architecture.md](docs/architecture.md).

## Layout

| Path | Purpose |
|---|---|
| `src/xtouch_daemon/hardware/` | The device: Mackie Control codec (`protocol`, pure functions), raw MIDI device (`midi`, `/dev/snd/midiC*D0`), a strip with its motor glide (`strip`), the connection with reconnects and sequences (`surface`), the self-test. |
| `src/xtouch_daemon/audio/` | `AudioState` model, `AudioBackend` protocol, `PulseBackend`, `pw-record` meters, MPRIS media players. |
| `src/xtouch_daemon/config/`, `config.example.toml` | pydantic configuration, split by topic (`files`, `model`, `sections`, `layout`, strip types, `inheritance`, `values`, `names`), and the example file. `config/presets.py` has the presets (`@browsers`, ...); `docs/configuration/presets.md` has their table, kept in line by a test. |
| `src/xtouch_daemon/strips/` | Strip controllers (`output`/`input`, `apps`, `auto`, `homeassistant`, `empty`, `voip`). |
| `src/xtouch_daemon/mqtt.py` | `MqttBridge`: the MQTT connection for Home Assistant (discovery, retained states, availability). |
| `src/xtouch_daemon/runtime/` | The running daemon: lifecycle (`daemon`: signals, reload, shutdown, sd_notify), `mixer` (feeds states and events to the controllers), `placement` (strips that collapse), `layouts` (switching and rules). |
| `src/xtouch_daemon/system/` | The system around it: `instance` (runtime file), `systemd` (incl. controlling the user service), `processes` (`/proc`), `launch` (starting a strip's `launch` detached from the daemon; tests use `FakeLauncher`, `conftest.no_launches` makes a real start fail). |
| `src/xtouch_daemon/live/` | The live view of the device for the GUI over a Unix socket: `messages`, `codec`, `server`. |
| `src/xtouch_daemon/cli/` | The CLI, one module per topic; `cli/__init__.py` puts the commands together. |
| `src/xtouch_daemon/voip/`, `integrations/mumble/` | VoIP providers (`bridge` socket for plugins, `demo`); the Mumble plugin (C, CMake, vendored `MumblePlugin.h`) and finding, building and installing its bundle (`voip/mumble.py`). `test/fake_mumble.c` is the host `tests/voip/test_mumble_plugin.py` loads it into. |
| `src/xtouch_daemon/gui/` | Optional `xtouch-daemon gui` (extra `gui`, PyQt6): `domain/` is toolkit-free and fully tested, `qt/` the widgets (`window/`, `preview/`, `pages/`, `fields/`, `theme/`). Forms come from the pydantic models, so new options need no GUI code. |
| `tests/` | Mirrors the source: `tests/<package>/test_<module>.py`. Fixtures in the `conftest.py` files (the guards in `tests/conftest.py`), fakes and helpers that tests import in `tests/support/` (e.g. the in-memory MQTT broker in `tests/support/mqtt.py`). |
| `docs/`, `zensical.toml` | The documentation site (Zensical, published to GitHub Pages by `.github/workflows/docs.yml`): `index.md`, `getting-started.md`, `configuration/*.md` (one page per topic), `home-assistant.md`, `gui.md`, `commands.md`, `troubleshooting.md`, `hardware.md`, `architecture.md`. Build it with `just docs`. |
| `packaging/` | Release tarballs (`build-release.sh`), the pinned commit of haad-mqtt-autodiscovery, the GUI's `.desktop` file, the AUR packages (`aur/`, `aur/publish.sh`). See [RELEASING.md](RELEASING.md). |

## Commands

```shell
uv sync
just test            # uv run pytest -n auto (in parallel); one test: uv run pytest tests/<package>/test_x.py -k name
just coverage        # in parallel too, fails below 90 %
just lint            # ruff check + ruff format --check + codespell
just typecheck       # pyright
just check           # all of the above, like CI
just docs            # builds the documentation site (strict: broken links fail)
```

## Rules

- Update the docs (README, `docs/`, `config.example.toml`, `CHANGELOG.md`) with every behaviour change. Verify every
  documented command and option against `cli/` and `config/`. Links between pages are relative (they work on
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
