default:
    @just --list

# install the project and the dev tools into .venv
sync:
    uv sync

# run the tests, in parallel (`-n0` runs them in this process, e.g. for a debugger)
test *ARGS:
    uv run pytest -n auto {{ARGS}}

# run the tests in parallel with coverage, fails below 90 %
coverage:
    uv run pytest -n auto --cov --cov-report=term-missing

# check style and formatting
lint:
    uv run ruff check
    uv run ruff format --check
    uvx codespell

# fix style issues and format the code
fmt:
    uv run ruff check --fix
    uv run ruff format

# check the types
typecheck:
    uv run pyright

# everything CI checks
check: lint typecheck coverage

# build the documentation site into site/ (strict: broken links fail)
docs:
    uv run --group docs zensical build --clean --strict

# serve the documentation on http://localhost:<port>, rebuilt on changes (8000 is often taken)
docs-serve port="8001":
    uv run --group docs zensical serve --dev-addr localhost:{{port}}

# render the screenshots of the documentation into docs/images/ (offscreen, with a demo configuration)
screenshot out="docs/images":
    uv run --extra gui python scripts/screenshot.py {{out}}

# run the daemon in the foreground
run *ARGS:
    uv run xtouch-daemon run {{ARGS}}

# build the release tarballs into dist/ (see RELEASING.md)
release-build out="dist":
    packaging/build-release.sh {{out}}

# pin haad-mqtt-autodiscovery to the commit checked out in ../haad-mqtt-autodiscovery (CI and releases build that one)
pin-haad-mqtt-autodiscovery:
    #!/usr/bin/env bash
    set -euo pipefail
    sibling=../haad-mqtt-autodiscovery
    if [ -n "$(git -C "$sibling" status --porcelain --untracked-files=no)" ]; then
        echo "warning: $sibling has uncommitted changes, which the pin does not include" >&2
    fi
    rev="$(git -C "$sibling" rev-parse HEAD)"
    if [ -z "$(git -C "$sibling" branch -r --contains "$rev")" ]; then
        echo "warning: $rev is not pushed yet, CI can't check it out" >&2
    fi
    echo "$rev" > packaging/haad-mqtt-autodiscovery.rev
    echo "packaging/haad-mqtt-autodiscovery.rev: $rev"
