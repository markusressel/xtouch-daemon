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


def test_check_config_describes_the_channels(tmp_path: Path) -> None:
    path = tmp_path / "flow.toml"
    path.write_text(
        '[channel.out]\ntype = "output"\nchoices = [{ label = "Phones", device = "a" },'
        ' { label = "Speaker", device = "b" }, { device = "bluez_output.*" }]\n'
        '[channel.buds]\ntype = "output"\ndevice = "bluez_output.*"\n'
        '[channel.video]\ntype = "apps"\nmatch = ["@video", "netflix"]\nlabel = "Video"\n'
        '[slots]\n1 = "out"\n2 = "buds if present"\n3 = "video"\n'
    )
    lines = invoke("check-config", "-c", str(path)).output.splitlines()
    assert lines[1] == "Channels:"
    assert lines[2].startswith("  out: output: Phones, Speaker or bluez_output.* (Select switches) (white, rec: ")
    assert lines[3].startswith("  buds: output bluez_output.*, select makes it the default (white, rec: recording")
    assert lines[4].startswith(
        "  video: 'Video' applications @video (vlc, mpv, celluloid, totem, kodi, haruna, clapper, mplayer), netflix ("
    )
    assert "What the slots show:" in lines


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
