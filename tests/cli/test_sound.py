"""
`list-devices` and `list-apps`.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.cli import invoke
from xtouch_daemon import cli
from xtouch_daemon.audio import pulse
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.cli import sound as sound_commands


@pytest.mark.usefixtures("audio")
def test_list_devices_marks_the_defaults() -> None:
    lines = invoke("list-devices").output.splitlines()

    assert lines == [
        "Outputs:",
        "  * speaker",
        "      speaker description, 50%, running",
        "    buds",
        "      buds description, 30%, muted",
        "Inputs:",
        "  * mic",
        "      mic description, 80%",
        "Profiles of alsa_card.pci, Family 17h/19h HD Audio Controller (speaker):",
        "  * output:analog-stereo",
        "      Analog Stereo Output",
        "    off",
        "      Off",
        "Profiles of bluez_card.buds:",
        "  * a2dp-sink",
        "      High Fidelity Playback",
    ]


@pytest.mark.usefixtures("audio", "config_file")
def test_list_apps_tells_which_channel_or_slot_takes_each_application() -> None:
    lines = invoke("list-apps").output.splitlines()

    assert lines == [
        "  Brave (@browsers)  binary: brave, 100%",
        "      goes to channel browser (Browser)",
        "  WEBRTC VoiceEngine (shown as 'Discord') (@voip)  binary: Discord, 60%, paused",
        "      goes to an auto slot",
        "  speech-dispatcher-espeak  binary: -, 100%",
        "      goes to ignored",
    ]


@pytest.mark.usefixtures("audio")
def test_without_auto_an_application_may_get_no_slot(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text("[slots]\n" + "".join(f'{slot} = "-"\n' for slot in range(1, 9)))

    assert "goes to no slot" in invoke("list-apps", "-c", str(path)).output


def test_list_apps_without_applications(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sound_commands, "_audio_state", lambda: AudioState())

    assert invoke("list-apps").output == "No application plays right now.\n"


def test_a_sound_server_that_can_not_be_reached_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unreachable(client_name: str) -> AudioState:
        raise ConnectionRefusedError("no socket")

    monkeypatch.setattr(pulse, "_read_state", unreachable)

    result = CliRunner().invoke(cli.main, ["list-devices"])

    assert result.exit_code == 1
    assert "can't reach the sound server (is pipewire-pulse running?): no socket" in result.output
