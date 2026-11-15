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
| `src/xtouch_daemon/daemon.py` | Lifecycle: signals, reload, shutdown, sd_notify. |
| `src/xtouch_daemon/instance.py`, `live.py` | The running daemon for the GUI: its runtime file, and the live view of the device over a Unix socket. |
| `src/xtouch_daemon/config.py`, `config.example.toml` | pydantic configuration and the example file. |
| `src/xtouch_daemon/cli.py`, `selftest.py`, `systemd.py` | CLI, device self-test, systemd integration (incl. controlling the user service). |
| `src/xtouch_daemon/gui/` | Optional `xtouch-daemon gui` (extra `gui`, PyQt6): `domain/` is toolkit-free and fully tested, `qt/` the widgets. Forms come from the pydantic models, so new options need no GUI code. |
| `tests/` | One test module per source module; fakes in `tests/conftest.py`, an in-memory MQTT broker in `tests/fake_mqtt.py`. |
| `docs/`, `zensical.toml` | The documentation site (Zensical, published to GitHub Pages by `.github/workflows/docs.yml`): `index.md`, `getting-started.md`, `configuration/*.md` (one page per topic), `home-assistant.md`, `gui.md`, `commands.md`, `troubleshooting.md`, `hardware.md`, `architecture.md`. Build it with `just docs`. |
| `contrib/xtouch-daemon.service` | systemd user unit, same as `systemd.UNIT_TEMPLATE`. |
| `packaging/` | Release tarballs (`build-release.sh`), the pinned commit of haad-mqtt-autodiscovery, the GUI's `.desktop` file, the AUR packages (`aur/`, `aur/publish.sh`). See [RELEASING.md](RELEASING.md). |

## Commands

```shell
uv sync
just test            # uv run pytest
just coverage        # fails below 90 %
just lint            # ruff check + ruff format --check
just typecheck       # pyright
just check           # all of the above, like CI
just docs            # builds the documentation site (strict: broken links fail)
```

## Rules

- Update the docs (README, `docs/`, `config.example.toml`, `CHANGELOG.md`) with every behaviour change. Verify every
  documented command and option against `cli.py` and `config.py`. Links between pages are relative (they work on
  GitHub and on the site); links to files outside `docs/` are absolute GitHub URLs. `just docs` must pass.
- Every behaviour change needs tests. Coverage stays ≥ 90 % (lines and branches).
- No hardware and no PipeWire/PulseAudio in unit tests: use a fake `AudioBackend`, a fake pulsectl connection, a
  recording surface, a FIFO or pty for MIDI, a fake `pw-record` script.
- Keep `contrib/xtouch-daemon.service` in sync with `systemd.UNIT_TEMPLATE`.
- Type hints everywhere; `ruff` and `pyright` must pass.
- Git: do not commit or push. The user handles all git operations.
