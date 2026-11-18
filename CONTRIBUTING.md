# Contributing

Bug reports and pull requests are welcome. For a larger change, open an issue first.

## Setup

You need [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just) (`make <target>` runs
`just <target>` too), and [haad-mqtt-autodiscovery](https://github.com/haad-org/haad-mqtt-autodiscovery) checked
out next to this repository (`../haad-mqtt-autodiscovery`): it is a path dependency, and `uv sync` fails without it.

```shell
uv sync          # creates .venv with the project and the dev tools
just test        # runs the tests
just check       # runs everything CI runs
```

| Recipe | What it does |
|---|---|
| `just sync` | Installs the project and the dev tools. |
| `just test [ARGS]` | Runs pytest in parallel (`-n auto`), e.g. `just test -k fader`. `uv run pytest -k fader` runs them in one process, quicker for a few tests and for a debugger. |
| `just coverage` | Runs the tests in parallel with coverage; fails below 90 % (lines and branches). |
| `just lint` | `ruff check`, `ruff format --check` and `codespell` (false positives go to `ignore-words-list` in `pyproject.toml`). |
| `just fmt` | Fixes what ruff can fix and formats the code. |
| `just typecheck` | `pyright`. |
| `just check` | `lint`, `typecheck` and `coverage`, like CI. |
| `just run [ARGS]` | Runs the daemon from the checkout, e.g. `just run -l debug`. |
| `just docs` | Builds the documentation site into `site/`; broken links fail. |
| `just release-build [OUT]` | Builds the release tarballs into `dist/` (see [RELEASING.md](RELEASING.md)). |
| `just pin-haad-mqtt-autodiscovery` | Pins the commit of `../haad-mqtt-autodiscovery` that CI and releases build. |
| `just docs-serve` | Serves the documentation on http://localhost:8001 (`just docs-serve 8002` for another port) and rebuilds it on changes. |
| `just docs-at <ref>` | Serves the documentation of a commit, tag or branch (`just docs-at 0.1.0 8002`), from a temporary worktree, with today's Zensical. |
| `just docs-versions` | Serves the published versions (the branch `gh-pages`, fetched from GitHub) with their version selector, as GitHub Pages does. |
| `just screenshot` | Renders the screenshots of the README and the documentation (`docs/images/`) offscreen, with the demo configuration in `scripts/screenshot.py`. Run it after changes to the look of the GUI and commit the images. |

Optional: `uvx pre-commit install` runs ruff before every commit.

In PyCharm, use `.venv` as the interpreter. `.run/` holds run configurations for `run`, `gui`, `test`, `check-config`,
`list-apps` and the tests; they run `python -m xtouch_daemon`. Stop the service first
(`systemctl --user stop xtouch-daemon`): only one program can use the device at a time.

## Rules

- Every behaviour change comes with tests, and with matching changes to `docs/` (the documentation site, see `zensical.toml`).
- The unit tests need neither the device nor a sound server: use the fakes in `tests/support/`. They see nothing
  of the machine they run on, and fail if they leave a process behind (see `no_host` and `no_leaks` in
  `tests/conftest.py`).
- Tests mirror the source: `src/xtouch_daemon/<package>/<module>.py` is tested in `tests/<package>/test_<module>.py`.
  Fixtures go into the `conftest.py` of the package that needs them, fakes and helpers that tests import into
  `tests/support/`.
- Asyncio tests run in virtual time ([looptime](https://github.com/nolar/looptime)): `asyncio.sleep(10)` takes no
  time. Tests with real processes or devices are marked `@pytest.mark.looptime(False)`.
- Coverage stays at 90 % or above.
- Type hints everywhere; `pyright` and `ruff` must pass.
- Add a line to `CHANGELOG.md` under the topmost version for anything a user notices.

To try a change on the device, stop the service first (`systemctl --user stop xtouch-daemon`): only one program can
open the device. Then `just run -l debug`.

See [docs/development/architecture.md](docs/development/architecture.md) for how the parts fit together.
