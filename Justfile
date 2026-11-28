default:
    @just --list

# install the project and the dev tools into .venv
sync:
    uv sync

# run the tests, in parallel (`-n0` runs them in this process, e.g. for a debugger)
test *ARGS:
    uv run pytest -n auto --dist worksteal {{ARGS}}

# run the tests in parallel with coverage: fails below 93 %, or below 98 % without the GUI's Qt parts (gui/qt, gui/quick)
coverage:
    uv run pytest -n auto --dist worksteal --cov --cov-report=term-missing
    uv run coverage report --omit="*/gui/qt/*,*/gui/quick/*" --fail-under=98 --format=total

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
docs: docs-icon
    uv run --group docs zensical build --clean --strict

# a cold read of a documentation page: a reader who knows nothing of the project reports where it fails a newcomer
cold-read page report="":
    scripts/cold-read.sh {{page}} {{report}}

# copy the icon of the project (the one in the package, which the GUI uses) to where the site takes it from
docs-icon:
    cp src/xtouch_daemon/gui/qt/theme/images/icon.svg docs/images/icon.svg

# write the JSON Schemas of the configuration and the voice chat bridge that the documentation publishes (a test
# checks that they are current)
schema:
    uv run xtouch-daemon schema > docs/config.schema.json
    uv run xtouch-daemon schema --bridge > docs/voice-chat-bridge.schema.json

# serve the documentation on http://localhost:<port>, rebuilt on changes (8000 is often taken)
docs-serve port="8001": docs-icon
    uv run --group docs zensical serve --dev-addr localhost:{{port}}

# serve the documentation of a commit, tag or branch on http://localhost:<port>, from a temporary worktree
docs-at ref port="8001":
    #!/usr/bin/env bash
    set -euo pipefail
    dir="$(mktemp -d)"
    git worktree add --detach "$dir" "{{ref}}"
    trap 'git worktree remove --force "$dir"' EXIT
    cd "$dir"
    # older refs have the copy committed
    if [ -f src/xtouch_daemon/gui/qt/theme/images/icon.svg ]; then cp src/xtouch_daemon/gui/qt/theme/images/icon.svg docs/images/icon.svg; fi
    # the Zensical of today: the ref may be older than the docs group
    uvx zensical serve --dev-addr localhost:{{port}}

# serve the published versions (the branch gh-pages, as fetched from origin) on http://localhost:<port>
docs-versions port="8001":
    git fetch origin gh-pages:gh-pages
    uv run --group docs mike serve --dev-addr localhost:{{port}}

# render the screenshots of the documentation into docs/images/ (offscreen, with a demo configuration)
screenshot out="docs/images":
    uv run --extra gui python scripts/screenshot.py {{out}}

# run the daemon in the foreground
run *ARGS:
    uv run xtouch-daemon run {{ARGS}}

# build the release tarballs into dist/ (see RELEASING.md)
release-build out="dist":
    packaging/build-release.sh {{out}}

# release step 1: version, uv.lock and changelog of a release, committed and pushed to main once you confirm (RELEASING.md)
release-prepare version:
    packaging/release.sh prepare {{version}}

# release step 2: tag, wait for the Release workflow, publish the AUR packages, bump the PKGBUILDs (RELEASING.md)
release-publish version:
    packaging/release.sh publish {{version}}

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
