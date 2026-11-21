# xtouch-daemon: Guide for AI Agents

Drives a Behringer X-Touch Extender (Mackie Control over USB MIDI) as a hardware mixer for PipeWire. Python 3.14 (haad-mqtt-autodiscovery, a path dependency in `../haad-mqtt-autodiscovery`, requires it),
uv, src layout. Start with [docs/development/architecture/index.md](docs/development/architecture/index.md).

## Layout

| Path | Purpose |
|---|---|
| `src/xtouch_daemon/hardware/` | The device: Mackie Control codec (`protocol`, pure functions), raw MIDI device (`midi`, `/dev/snd/midiC*D0`), a strip with its motor glide (`strip`), the connection with reconnects and sequences (`surface`), the self-test. |
| `src/xtouch_daemon/audio/` | `AudioState` model, `AudioBackend` protocol, `PulseBackend`, `pw-record` meters, MPRIS media players. |
| `src/xtouch_daemon/config/`, `config.example.toml` | pydantic configuration, split by topic (`files`, `model`, `sections`, `layout`, strip types, `inheritance`, `values`, `names`), and the example file. `config/presets.py` has the presets (`@browsers`, ...); `docs/configuration/presets.md` has their table, kept in line by a test. |
| `src/xtouch_daemon/strips/` | Strip controllers (`output`/`input`, `apps`, `auto`, `homeassistant`, `empty`, `voip`). |
| `src/xtouch_daemon/slots/` | Channels, pools, states, slots and their resolver (`docs/development/design/slots/index.md`), pure: `daemon/slots` runs it on the device, the GUI's Simulate and `xtouch-daemon simulate` and `observe` drive it too. |
| `src/xtouch_daemon/homeassistant/` | The API of Home Assistant (`[homeassistant]`): the WebSocket `client` (`HomeAssistant`, one connection, all entities, services; `fetch_entities()`), `states`, `parts` (what a part shows), `domains` (values and services by domain). `strips/entity.py` binds parts to entities. Tests use the in-memory Home Assistant in `tests/support/homeassistant.py`. |
| `src/xtouch_daemon/mqtt.py` | `MqttBridge`: the MQTT connection for Home Assistant (discovery, retained states, availability). |
| `src/xtouch_daemon/daemon/` | The running daemon (the GUI never imports it): `lifecycle` (signals, reload, shutdown, sd_notify), `rig` (a configuration on one surface), `desk` (the 8 strips and the hands on them), `slots` (channels, states and slots on the device), `binder` (what each slot shows), `controls`, `twin` (the virtual twin for previews), `homeassistant` (its entities), `slot_files` and `device_memory` (what it keeps across restarts). |
| `src/xtouch_daemon/system/` | The system around it: `instance` (runtime file), `systemd` (incl. controlling the user service), `processes` (`/proc`), `launch` (starting a strip's `launch` detached from the daemon; tests use `FakeLauncher`, `conftest.no_launches` makes a real start fail). |
| `src/xtouch_daemon/live/` | The live view of the device for the GUI over a Unix socket: `messages`, `codec`, `server`, `log` (the log of the daemon for the GUI). |
| `src/xtouch_daemon/cli/` | The CLI, one module per topic; `cli/__init__.py` puts the commands together. |
| `src/xtouch_daemon/voip/`, `integrations/mumble/`, `integrations/teamspeak/` | VoIP providers (`bridge` socket for plugins, `demo`), the messages of the bridge as pydantic models (`protocol`, the source of `docs/voice-chat-bridge.schema.json`); the Mumble plugin (C, CMake, vendored `MumblePlugin.h`) and finding, building and installing its bundle (`voip/mumble.py`). `test/fake_mumble.c` is the host `tests/voip/test_mumble_plugin.py` loads it into. The TeamSpeak 3 plugin (C, CMake; the build downloads TeamSpeak's SDK headers into the git-ignored `integrations/teamspeak/sdk/`, they can't be vendored) and installing it into `~/.ts3client/plugins` (`voip/teamspeak.py`); its host is `test/fake_teamspeak.c`. |
| `src/xtouch_daemon/gui/` | Optional `xtouch-daemon gui` (extra `gui`, PyQt6): `domain/` is toolkit-free and fully tested, `qt/` the widgets (`window/`, `preview/`, `pages/`, `fields/`, `theme/`). Forms come from the pydantic models, so new options need no GUI code. |
| `tests/` | Mirrors the source: `tests/<package>/test_<module>.py`. Fixtures in the `conftest.py` files (the guards in `tests/conftest.py`), fakes and helpers that tests import in `tests/support/` (e.g. the in-memory MQTT broker in `tests/support/mqtt.py`). |
| `docs/`, `zensical.toml` | The documentation site (Zensical, published to GitHub Pages by `.github/workflows/docs.yml`): sections as folders, as in the navigation: `getting-started/` (install, first steps, without a device), `guides/` (GUI, Home Assistant, Mumble, troubleshooting), `configuration/` (an overview, `slots.md`, `channels/` with a page per type, `strip/` for encoders and LEDs, presets, behavior), `reference/` (commands, hardware and protocol, the voice chat bridge), `development/` (an index, `architecture/` with a page per topic, `design/` with `slots/`, `history/` for replaced designs). A new page goes into the section of its kind, and into `nav` of `zensical.toml`. Build it with `just docs`. |
| `packaging/` | Release tarballs (`build-release.sh`), the pinned commit of haad-mqtt-autodiscovery, the GUI's `.desktop` file, the AUR packages (`aur/`, `aur/publish.sh`). See [RELEASING.md](RELEASING.md). |

## Commands

```shell
uv sync
just test            # uv run pytest -n auto --dist worksteal (in parallel); one test: uv run pytest tests/<package>/test_x.py -k name
just coverage        # in parallel too, fails below 90 %
just lint            # ruff check + ruff format --check + codespell
just typecheck       # pyright
just check           # all of the above, like CI
just docs            # builds the documentation site (strict: broken links fail)
just screenshot      # renders docs/images/ (README and docs) offscreen from scripts/screenshot.py: after changes to the look of the GUI
```

## Rules

- Update the docs (README, `docs/`, `config.example.toml`, `CHANGELOG.md`) with every behaviour change. Verify every
  documented command and option against `cli/` and `config/`. Links between pages are relative (they work on
  GitHub and on the site); links to files outside `docs/` are absolute GitHub URLs. `just docs` must pass.
- Every behaviour change needs tests. Coverage stays ≥ 90 % (lines and branches).
- The C plugins are tested end to end (built with CMake, loaded into `fake_mumble` or `fake_teamspeak`, against
  `BridgeProvider`); those tests are skipped without cmake and a C compiler (the TeamSpeak ones also without its SDK).
  Never test against a real Mumble or TeamSpeak in the tests.
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
- GUI: never show a popup window (`Qt.WindowType.Popup`): it grabs the keyboard and the mouse, on X11 the whole
  display, so screenshot tools and the keys of the window manager stop working (and Alt closes a `QMenu`). Everything
  opens inside the window: details a click away are popovers (`gui/qt/fields/popover.py`); menus are `QMenu`s that are
  never shown, opened by `show_menu`/`attach_menu` and the `MenuBar` of `gui/qt/fields/menu.py` (`describe` gives an
  entry a line under it); drop-down lists are `Choice` (`gui/qt/fields/choice.py`), never a plain `QComboBox`;
  suggestions under a field are a `SuggestionList` (`gui/qt/fields/suggestions.py`, used by `NameCompleter`), never a
  `QCompleter`. No `QMenu.exec`/`popup`, `setMenu`, `menuBar()`. `conftest.no_popups` fails a test in which a popup
  shows.
- Git: on a branch, commit and push the finished, checked work; on `main` only when the user asks. Never force-push.

## Writing docs

The pages of `docs/` are for someone who meets the project for the first time. The terse style of the help texts
(below) is for one line under a field; it doesn't fit a page. On a page:

- Full sentences with their verbs. Never leave a verb out of a list ("`auto` and `apps` the applications that play"
  reads as a puzzle); a list of several things is a bulleted list.
- Explain a term with things the reader knows, the first time it appears, then an example. Never explain a term with
  two other new terms.
- Show before you tell: each concept gets a short example of the configuration, and the text says which parts of the
  example are which ("`buds` and `game` are channels, `auto` is a pool").
- A page answers the questions of its own task, at the level of its section (below). A link sends the reader on
  for details, not for what they need to finish the task here.
- Concrete beats general when it is as short: "your headphones", not "a device"; "while a game runs", not "in a
  situation".
- Examples and the text agree: a comment in an example says no less than the table it illustrates.
- One word for one thing, and never one word for two things:
    - The hardware is "the X-Touch" ("the X-Touch Extender" the first time on a page), never a bare "the device",
      "the surface" or "the extender". A strip is one of its 8 columns.
    - The GUI's names stay as the GUI shows them: the window "Device", the "virtual device" (the X-Touch drawn in
      the window), explained the first time on a page.
    - A sound device is "an output" (headphones, speakers) or "an input" (a microphone), or "a sound device" when
      it can be either. Never a bare "device" for it. Names in the configuration stay as they are: the types
      `output` and `input`, the pool `devices`, the option `device`.
    - "Application" for a program that plays sound, "stream" only where one application has several.
- Each detail has one home, by section, and the others link to it:
    - The front page, Concepts and Getting started: what it is, why, and one example. No defaults, timings or edge
      cases.
    - Configuration: every option, what it does, its default, an example.
    - Guides: one goal from start to end; options only as far as the goal needs them.
    - Reference: everything else: edge cases, timings, the protocol, every command and its output.
- Check a page with a cold read: `just cold-read docs/<page>.md` runs a reader that knows only the front page,
  Concepts and that page, and reports what it understood, what it had to guess, the sentences it stumbled over (with
  a severity) and contradictions. A page is done when the reader explains it back right and reports no severity 2 or 3.
  A cold reader can't see a vague word or a detail on the wrong level (a newcomer guesses and reads on): that takes
  a review by someone who knows the code.

## Writing help

The help of an option is its attribute docstring (the GUI shows it under the field); what a value of a choice does is
in its `Meanings`. Write them for someone who looks at the device, after
the [Microsoft Writing Style Guide](https://learn.microsoft.com/en-us/style-guide/welcome/) (UI text), the
[Google developer documentation style guide](https://developers.google.com/style) and ASD-STE100 (Simplified
Technical English):

- Start with what changes on the device (or in the window), as the user sees it: "The backlight of the LCD.", not
  how the daemon does it. Then what the other values do, if that is not plain.
- Short sentences (at most 20 words), one idea each, active voice, present tense. Two or three sentences in all.
- A switch says what On does ("Select makes the device the default."); not "Whether ...". Off only if it is not
  the opposite.
- Numbers say their unit first: "Seconds ...", "The volume, in percent, ...".
- Not the default: the GUI adds "Default: ..." itself. Only a default that depends on something else ("by default
  `behavior.max_volume`").
- One example at most, at the end, with "e.g.".
- Edge cases, reasons and how it works go to the docs page the "Learn more" link opens.
- The same word for the same thing, the words of the GUI: state, mode, channel, pool, slot, strip, candidate.
  The GUI and the docs color them (and their sections in `code`, e.g. `[state.gaming]`, the pools `apps`, `people`,
  `devices`, and `present`; the docs by `docs/javascripts/entities.js`, with the words of `help_text`), so write
  them out; people and applications have the color of the channels. Write the controls of the device as they are
  printed (Select, Mute, Solo, Rec) or as words (fader, encoder, LCD): they stand out too.
- Options, values, commands and sections in backticks.
- Headings and titles (popovers, their rows, pages, docks) are short noun phrases in sentence case: "Connections",
  "Mode and states", "File"; no "The ...", no "What ...". A pill's popover doesn't repeat the pill: it explains it.
