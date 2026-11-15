default:
    @just --list

# install the project and the dev tools into .venv
sync:
    uv sync

# run the tests
test *ARGS:
    uv run pytest {{ARGS}}

# run the tests with coverage, fails below 90 %
coverage:
    uv run pytest --cov --cov-report=term-missing

# check style and formatting
lint:
    uv run ruff check
    uv run ruff format --check

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

# run the daemon in the foreground
run *ARGS:
    uv run xtouch-daemon run {{ARGS}}
