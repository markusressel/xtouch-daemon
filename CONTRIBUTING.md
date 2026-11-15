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
| `just test [ARGS]` | Runs pytest, e.g. `just test -k fader`. |
| `just coverage` | Runs the tests with coverage; fails below 90 % (lines and branches). |
| `just lint` | `ruff check` and `ruff format --check`. |
| `just fmt` | Fixes what ruff can fix and formats the code. |
| `just typecheck` | `pyright`. |
| `just check` | `lint`, `typecheck` and `coverage`, like CI. |
| `just run [ARGS]` | Runs the daemon from the checkout, e.g. `just run -l debug`. |

Optional: `uvx pre-commit install` runs ruff before every commit.

In PyCharm, use `.venv` as the interpreter. `.run/` holds run configurations for `run`, `test`, `check-config`,
`list-apps` and the tests; they run `python -m xtouch_daemon`. Stop the service first
(`systemctl --user stop xtouch-daemon`): only one program can use the device at a time.

## Rules

- Every behaviour change comes with tests, and with matching changes to the README and `docs/`.
- The unit tests need neither the device nor a sound server: use the fakes in `tests/conftest.py`.
- Coverage stays at 90 % or above.
- Type hints everywhere; `pyright` and `ruff` must pass.
- Add a line to `CHANGELOG.md` under the topmost version for anything a user notices.

To try a change on the device, stop the service first (`systemctl --user stop xtouch-daemon`): only one program can
open the device. Then `just run -l debug`.

See [docs/architecture.md](docs/architecture.md) for how the parts fit together.
