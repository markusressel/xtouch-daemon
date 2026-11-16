"""
`init-config` and `check-config`.
"""

from pathlib import Path

from click.testing import CliRunner

from tests.support.cli import CONFIG, invoke
from xtouch_daemon import cli


def test_check_config_shows_what_each_strip_does(config_file: Path) -> None:
    result = invoke("check-config")

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        f"{config_file}: valid",
        "  1. 'Out' the default output (white, rec: recording, solo: off, encoder: balance)",
        "  2. input mic (white, no meter, rec: off, solo: muted, encoder: balance)",
        "  3. 'Browser' applications brave, firefox (yellow, rec: recording, solo: off, encoder: media)",
        "  4. empty",
        "  5. 'Lights' Home Assistant, entities *.*_strip_5_* (white)",
        "  6. Home Assistant, entities *.*_desk_* (blue)",
        *[
            f"  {number}. the next application that plays (white, rec: recording, solo: off, encoder: pick)"
            for number in range(7, 9)
        ],
    ]


def test_check_config_without_a_file_checks_the_defaults() -> None:
    result = invoke("check-config")

    assert result.exit_code == 0
    assert result.output.startswith("No configuration file, the defaults: valid\n")
    assert "select makes it the default" not in result.output


def test_a_named_device_with_select_says_so(tmp_path: Path) -> None:
    path = tmp_path / "other.toml"
    path.write_text('[[strip]]\ntype = "output"\ndevice = "buds"\nfader = "homeassistant"\n[mqtt]\nhost = "b"\n')

    assert (
        "1. output buds, select makes it the default (white, rec: recording, solo: off, encoder: volume, "
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
    assert invoke("check-config").output.startswith(f"{config_home}: valid")


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
