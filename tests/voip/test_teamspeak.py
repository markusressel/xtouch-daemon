import subprocess
from pathlib import Path
from typing import Any

import pytest

from xtouch_daemon.voip import teamspeak


@pytest.fixture(autouse=True)
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home, share directories and a PATH of its own: what the tests put there, nothing of this machine."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(teamspeak, "SHARE_DIRS", (tmp_path / "usr" / "share" / "xtouch-daemon",))
    monkeypatch.setattr(teamspeak, "INSTALL_DIRS", (tmp_path / "opt" / "teamspeak3",))
    monkeypatch.setattr(teamspeak, "SOURCE_DIR", tmp_path / "src")
    monkeypatch.setattr(teamspeak.shutil, "which", lambda name: None)
    return tmp_path


def touch(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def programs(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    monkeypatch.setattr(teamspeak.shutil, "which", lambda name: f"/usr/bin/{name}" if name in names else None)


def test_the_plugin_of_a_release_comes_before_a_built_one(machine: Path):
    assert teamspeak.find_library() is None
    built = touch(machine / "src" / "build" / teamspeak.LIBRARY_NAME)
    assert teamspeak.find_library() == built
    released = touch(machine / "usr" / "share" / "xtouch-daemon" / teamspeak.LIBRARY_NAME)
    assert teamspeak.find_library() == released
    assert teamspeak.find_library([built]) == built


def test_the_plugin_in_teamspeak(machine: Path):
    assert teamspeak.installed_plugin() is None
    installed = touch(machine / "home" / ".ts3client" / "plugins" / teamspeak.LIBRARY_NAME)
    assert teamspeak.installed_plugin() == installed


@pytest.mark.parametrize("found_by", ["command", "directory", "settings"])
def test_teamspeak_is_found_by_its_command_its_directory_or_its_settings(
    found_by: str, machine: Path, monkeypatch: pytest.MonkeyPatch
):
    assert not teamspeak.teamspeak_installed()
    if found_by == "command":
        programs(monkeypatch, "teamspeak3")
    elif found_by == "directory":
        (machine / "opt" / "teamspeak3").mkdir(parents=True)
    else:
        (machine / "home" / ".ts3client").mkdir(parents=True)
    assert teamspeak.teamspeak_installed()


def test_the_setup_tells_what_there_is_to_build_and_install(machine: Path, monkeypatch: pytest.MonkeyPatch):
    assert teamspeak.setup() == teamspeak.Setup(library=None, buildable=False, installed=None, teamspeak=False)
    assert not teamspeak.setup().installable
    touch(machine / "src" / "CMakeLists.txt")
    programs(monkeypatch, "cmake", "cc", "teamspeak3")
    found = teamspeak.setup()
    assert found.buildable
    assert found.teamspeak
    assert found.installable
    programs(monkeypatch, "cmake", "teamspeak3")
    assert not teamspeak.can_build()


class Runs(list[list[str]]):
    """The commands `subprocess.run` was given, answered with `returncode` and `output` (stderr)."""

    def __init__(self, returncode: int = 0, output: str = "", makes: Path | None = None):
        super().__init__()
        self.returncode = returncode
        self.output = output
        self.makes = makes

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.append(command)
        if self.makes is not None and command[1] == "--build":
            touch(self.makes)
        return subprocess.CompletedProcess(command, self.returncode, "", self.output)


def test_a_build_needs_the_sources_and_says_why_it_failed(machine: Path, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(teamspeak.TeamSpeakError, match="needs its sources"):
        teamspeak.build()
    touch(machine / "src" / "CMakeLists.txt")
    programs(monkeypatch, "cmake", "gcc")
    library = machine / "src" / "build" / teamspeak.LIBRARY_NAME
    runs = Runs(makes=library)
    monkeypatch.setattr(teamspeak.subprocess, "run", runs)
    assert teamspeak.build() == library
    assert runs[1] == ["cmake", "--build", str(machine / "src" / "build")]

    library.unlink()
    monkeypatch.setattr(teamspeak.subprocess, "run", Runs())
    with pytest.raises(teamspeak.TeamSpeakError, match="The build made no"):
        teamspeak.build()
    monkeypatch.setattr(
        teamspeak.subprocess,
        "run",
        Runs(1, "CMake Error at CMakeLists.txt:51 (message):\n  Can't download TeamSpeak's plugin SDK\n\n"),
    )
    with pytest.raises(teamspeak.TeamSpeakError, match="cmake -S failed: Can't download TeamSpeak's plugin SDK"):
        teamspeak.build()
    monkeypatch.setattr(teamspeak.subprocess, "run", Runs(2))
    with pytest.raises(teamspeak.TeamSpeakError, match="cmake -S failed: 2"):
        teamspeak.build()


def test_install_copies_the_plugin_and_builds_first_without_one(machine: Path, monkeypatch: pytest.MonkeyPatch):
    touch(machine / "usr" / "share" / "xtouch-daemon" / teamspeak.LIBRARY_NAME, "v1")
    with pytest.raises(teamspeak.TeamSpeakError, match="TeamSpeak 3 is not installed"):
        teamspeak.install()
    programs(monkeypatch, "teamspeak3")
    message = teamspeak.install()
    assert "Reload All" in message
    installed = machine / "home" / ".ts3client" / "plugins" / teamspeak.LIBRARY_NAME
    assert installed.read_text() == "v1"
    assert installed.stat().st_mode & 0o777 == 0o755
    # replaced as a whole, nothing left over
    assert [path.name for path in installed.parent.iterdir()] == [teamspeak.LIBRARY_NAME]

    # without a plugin, or asked to: built first
    built = machine / "src" / "build" / teamspeak.LIBRARY_NAME
    monkeypatch.setattr(teamspeak, "build", lambda: touch(built, "v2"))
    teamspeak.install(rebuild=True)
    assert installed.read_text() == "v2"


def test_a_plugin_that_can_not_be_installed_says_why(machine: Path, monkeypatch: pytest.MonkeyPatch):
    programs(monkeypatch, "teamspeak3")
    touch(machine / "usr" / "share" / "xtouch-daemon" / teamspeak.LIBRARY_NAME)
    # the plugin directory is a file
    touch(machine / "home" / ".ts3client" / "plugins")
    with pytest.raises(teamspeak.TeamSpeakError, match="Can't install the plugin into"):
        teamspeak.install()
