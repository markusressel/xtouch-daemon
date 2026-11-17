"""
`init-config` and `check-config`.
"""

from pathlib import Path

from click.testing import CliRunner

from tests.support.cli import CONFIG, invoke
from xtouch_daemon import cli


def test_check_config_shows_the_channels_and_the_slots(config_file: Path) -> None:
    result = invoke("check-config")

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        f"{config_file}: valid",
        "Channels:",
        "  out: 'Out' the default output (white, rec: recording, solo: off, encoder: balance)",
        "  mic: input mic (white, no meter, rec: off, solo: muted, encoder: balance)",
        "  browser: 'Browser' applications brave, firefox (yellow, rec: recording, solo: off, encoder: media)",
        "  lights: 'Lights' Home Assistant, entities *.*_lights_* (white)",
        "  desk: Home Assistant, entities *.*_desk_* (blue)",
        "What the slots show:",
        "when     1    2    3        4  5       6     7-8",
        "default  out  mic  browser  -  lights  desk  auto",
    ]


def test_check_config_of_a_file_without_channels(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text("")
    assert invoke("check-config", "-c", str(path)).output.splitlines()[1:] == [
        "What the slots show:",
        "when     1-8",
        "default  auto",
    ]


def test_check_config_without_a_file_checks_the_defaults() -> None:
    result = invoke("check-config")

    assert result.exit_code == 0
    assert result.output.startswith("No configuration file, the defaults: valid\n")
    assert "select makes it the default" not in result.output


def test_a_named_device_with_select_says_so(tmp_path: Path) -> None:
    path = tmp_path / "other.toml"
    path.write_text(
        '[channel.buds]\ntype = "output"\ndevice = "buds"\nfader = "homeassistant"\n[mqtt]\nhost = "b"\n'
        '[slots]\n1 = "buds"\n'
    )

    assert (
        "buds: output buds, select makes it the default (white, rec: recording, solo: off, encoder: volume, "
        "fader: homeassistant)" in invoke("check-config", "-c", str(path)).output
    )


def test_check_config_reports_errors(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[behavior]\nmax_volume = 300\n")

    result = CliRunner().invoke(cli.main, ["check-config", "--config", str(path)])

    assert result.exit_code == 1
    assert "behavior.max_volume" in result.output


def test_init_config_writes_the_example(config_home: Path) -> None:
    result = invoke("init-config")

    assert result.exit_code == 0
    assert f"Wrote {config_home}" in result.output
    output = invoke("check-config").output
    assert output.startswith(f"{config_home}: valid")
    assert "What the slots show:" in output


def test_init_config_with_strips(tmp_path: Path) -> None:
    path = tmp_path / "strips.toml"
    assert invoke("init-config", "--strips", str(path)).exit_code == 0
    assert "[[strip]]" in path.read_text()


def test_migrate_config_writes_the_new_file_next_to_the_old_one(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(OLD)
    result = invoke("migrate-config", "-c", str(path))
    new = tmp_path / "config.slots.toml"
    assert result.output.splitlines() == [
        f"Wrote {new}",
        "  - strip 2: collapse: speaker_2 stays on its slot while present, auto otherwise (nothing shifts; a pool of "
        "channels fills slots in order)",
        "  - The layouts are modes: select.<namespace>_mode replaces select.<namespace>_layout in Home Assistant "
        "(change automations that use it); the layout kept for the next start is not carried over",
        f"Check it with: xtouch-daemon check-config -c {new}",
    ]
    assert path.read_text() == OLD
    assert "What the slots show:" in invoke("check-config", "-c", str(new)).output
    # once more: the new file is there
    again = CliRunner().invoke(cli.main, ["migrate-config", "-c", str(path)])
    assert "exists already (--force overwrites it)" in again.output
    assert invoke("migrate-config", "-c", str(path), "--force").exit_code == 0
    other = tmp_path / "other.toml"
    assert invoke("migrate-config", "-c", str(path), "-o", str(other)).exit_code == 0
    assert other.read_text() == new.read_text()


def test_migrate_config_in_place_keeps_the_old_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(OLD)
    result = invoke("migrate-config", "-c", str(path), "--in-place")
    assert result.output.startswith(f"Kept the old file as {tmp_path / 'config.layouts.toml'}\nWrote {path}\n")
    assert (tmp_path / "config.layouts.toml").read_text() == OLD
    assert "[slots]" in path.read_text()
    # the old file is there already; a file of slots can't be migrated
    path.write_text(OLD)
    assert (
        "config.layouts.toml exists already"
        in CliRunner().invoke(cli.main, ["migrate-config", "-c", str(path), "--in-place"]).output
    )
    migrated = CliRunner().invoke(cli.main, ["migrate-config", "-c", str(tmp_path / "config.slots.toml")])
    assert "does not exist" in migrated.output
    invoke("migrate-config", "-c", str(path))
    again = CliRunner().invoke(cli.main, ["migrate-config", "-c", str(tmp_path / "config.slots.toml")])
    assert "has channels, states and slots already" in again.output
    both = CliRunner().invoke(cli.main, ["migrate-config", "-c", str(path), "--in-place", "-o", "x.toml"])
    assert "--output or --in-place, not both" in both.output


OLD = """[[strip]]
type = "output"
label = "Speaker"

[[strip]]
type = "output"
device = "buds"
label = "Speaker"
collapse = true

[[layout]]
name = "gaming"
"""


def test_init_config_does_not_overwrite_without_force(config_file: Path) -> None:
    result = CliRunner().invoke(cli.main, ["init-config"])
    assert result.exit_code == 1
    assert "--force" in result.output
    assert config_file.read_text() == CONFIG

    assert invoke("init-config", "--force").exit_code == 0
    assert config_file.read_text() != CONFIG


def test_init_config_writes_to_a_given_path(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b.toml"
    assert invoke("init-config", str(path)).exit_code == 0
    assert path.exists()
