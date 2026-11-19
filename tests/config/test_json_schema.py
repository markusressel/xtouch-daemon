"""
The JSON Schema of the configuration file (`config.json_schema`): it is current where the documentation publishes it,
it takes every file the daemon takes (the example, those of the documentation, the short forms of options), and it
marks the mistakes an editor should mark while typing.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tests.support.cli import invoke
from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.files import example_config, parse_config
from xtouch_daemon.config.json_schema import SCHEMA_URL, config_schema, schema_text

ROOT = Path(__file__).parent.parent.parent
DOCS = ROOT / "docs"
VALIDATOR = jsonschema.Draft202012Validator(config_schema())


def problems(text: str) -> list[str]:
    """The mistakes the schema finds in `text`, as `path: message`."""
    found = VALIDATOR.iter_errors(tomllib.loads(text))
    return sorted(f"{'.'.join(str(part) for part in error.absolute_path)}: {error.message}" for error in found)


def documented_configs() -> list[tuple[str, str]]:
    """The TOML of the pages of the documentation, by page and number."""
    configs: list[tuple[str, str]] = []
    for page in sorted(DOCS.rglob("*.md")):
        for number, match in enumerate(re.finditer(r"```toml\n(.*?)```", page.read_text(encoding="utf-8"), re.S)):
            configs.append((f"{page.relative_to(DOCS)}#{number}", match[1]))
    return configs


def test_the_published_schema_is_current():
    # `just schema` writes it
    assert (DOCS / "config.schema.json").read_text(encoding="utf-8") == schema_text()


def test_it_is_a_valid_schema():
    jsonschema.Draft202012Validator.check_schema(config_schema())


def test_the_command_prints_it():
    result = invoke("schema")
    assert result.exit_code == 0
    assert result.output == schema_text()


def test_the_example_points_to_it_and_matches_it():
    assert example_config().splitlines()[0] == f"#:schema {SCHEMA_URL}"
    assert problems(example_config()) == []


@pytest.mark.parametrize(("page", "text"), documented_configs(), ids=lambda value: value if "#" in value else "")
def test_it_takes_the_files_of_the_documentation_that_the_daemon_takes(page: str, text: str):
    try:
        parse_config(text)
    except ConfigError:
        pytest.skip("a part of a file, or a mistake on purpose")
    assert problems(text) == []


SHORT_FORMS = """
[switching]
chord = { strips = [1, 8], action = "toggle:call" }

[channel.out]
type = "output"
device = "alsa_output.usb-*"
select = true
rec = "playing"

[channel.web]
type = "apps"
match = ["@browsers"]
label = "Web"
launch = "firefox --new-window"
solo = { press = "mute_others", led = "muted" }

[channel.alice]
type = "person"
person = "Alice"

[pool.people]
color = "cyan"

[pool.friends]
kind = "people"
people = "Alice"

[pool.devices]
exclude = "bluez_*"

[pool.games]
kind = "apps"
match = ["steam"]
color = "red"

[state.call]
voice_chat = true

[slots]
1 = "games"
2 = ["web if call", { show = "out", color = "green", when = "not call" }]
8 = "out"

[controls]
4 = { fader = "homeassistant" }
5 = [{ select = "cycle_modes", when = "call" }, { select = { launch = ["pavucontrol"] } }]

[mqtt]
host = "localhost"
"""


def test_it_takes_the_short_forms_of_options():
    parse_config(SHORT_FORMS)
    assert problems(SHORT_FORMS) == []


@pytest.mark.parametrize(
    ("text", "mistake"),
    [
        ('[channel.out]\ntype = "output"\ncolour = "red"', "channel.out: Additional properties"),
        ('[channel.out]\ntype = "speaker"', "channel.out.type: 'speaker' is not one of"),
        ("[channel.Out]\ntype = 'output'", "channel: 'Out' does not match"),
        ('[slots]\n9 = "auto"', "slots: '9' does not match"),
        ('[pool.apps]\nchannels = ["out"]', "pool.apps: Additional properties"),
        ('[pool.mine]\nkind = "devices"', "pool.mine: {'kind': 'devices'} is not valid"),
        ("[state.call]\nvoice_chat = 1", "state.call.voice_chat: 1 is not of type 'boolean'"),
        ('[controls]\n4 = { mute = "homeassistant" }', "controls.4: {'mute': 'homeassistant'} is not valid"),
        ("[behavior]\nmax_volume = 2", "behavior.max_volume: 2 is less than the minimum"),
        ('[strip]\ntype = "output"', ": Additional properties are not allowed ('strip' was unexpected)"),
    ],
)
def test_it_marks_mistakes(text: str, mistake: str):
    found = problems(text)
    assert any(problem.startswith(mistake) for problem in found), found


def test_options_have_their_help():
    schema: dict[str, Any] = config_schema()
    channel = schema["properties"]["channel"]["additionalProperties"]
    assert "description" in schema["$defs"][channel["properties"]["color"]["$ref"].removeprefix("#/$defs/")]
    assert "description" in channel["properties"]["tags"]
    assert "description" in schema["$defs"]["StateConfig"]["properties"]["voice_chat"]
