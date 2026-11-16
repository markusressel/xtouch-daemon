import subprocess
from pathlib import Path
from typing import Any

import pytest

from xtouch_daemon import mumble


@pytest.fixture(autouse=True)
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home, share directories and a PATH of its own: what the tests put there, nothing of this machine."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(mumble, "SHARE_DIRS", (tmp_path / "usr" / "share" / "xtouch-daemon",))
    monkeypatch.setattr(mumble, "FLATPAK_SYSTEM", tmp_path / "var" / "lib" / "flatpak")
    monkeypatch.setattr(mumble, "SOURCE_DIR", tmp_path / "src")
    monkeypatch.setattr(mumble.shutil, "which", lambda name: None)
    return tmp_path


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def programs(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    monkeypatch.setattr(mumble.shutil, "which", lambda name: f"/usr/bin/{name}" if name in names else None)


def test_the_bundle_of_a_release_comes_before_a_built_one(machine: Path):
    assert mumble.find_bundle() is None
    built = touch(machine / "src" / "build" / mumble.BUNDLE_NAME)
    assert mumble.find_bundle() == built
    released = touch(machine / "usr" / "share" / "xtouch-daemon" / mumble.BUNDLE_NAME)
    assert mumble.find_bundle() == released
    assert mumble.find_bundle([built]) == built


def test_the_plugin_in_mumble(machine: Path, monkeypatch: pytest.MonkeyPatch):
    assert mumble.installed_plugin() is None
    flatpak = touch(
        machine / "home" / ".var" / "app" / mumble.FLATPAK_ID / "data/Mumble/Mumble/Plugins" / mumble.LIBRARY_NAME
    )
    assert mumble.installed_plugin() == flatpak
    monkeypatch.setenv("XDG_DATA_HOME", str(machine / "data"))
    native = touch(machine / "data" / "Mumble/Mumble/Plugins" / mumble.LIBRARY_NAME)
    assert mumble.installed_plugin() == native


def test_how_mumble_opens_the_bundle(machine: Path, monkeypatch: pytest.MonkeyPatch):
    bundle = Path("/b.mumble_plugin")
    assert mumble.mumble_command(bundle) is None
    programs(monkeypatch, "flatpak")
    # flatpak, but no Mumble in it
    assert mumble.mumble_command(bundle) is None
    (machine / "home" / ".local" / "share" / "flatpak" / "app" / mumble.FLATPAK_ID).mkdir(parents=True)
    assert mumble.mumble_command(bundle) == [
        "flatpak",
        "run",
        "--file-forwarding",
        mumble.FLATPAK_ID,
        "-m",
        "@@",
        "/b.mumble_plugin",
        "@@",
    ]
    programs(monkeypatch, "flatpak", "mumble")
    assert mumble.mumble_command(bundle) == ["mumble", "-m", "/b.mumble_plugin"]


def test_what_there_is(machine: Path, monkeypatch: pytest.MonkeyPatch):
    assert mumble.setup() == mumble.Setup(bundle=None, buildable=False, installed=None, mumble=False)
    assert not mumble.setup().installable
    touch(machine / "src" / "CMakeLists.txt")
    programs(monkeypatch, "cmake", "cc", "mumble")
    found = mumble.setup()
    assert found.buildable
    assert found.mumble
    assert found.installable
    programs(monkeypatch, "cmake", "mumble")
    assert not mumble.can_build()


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


def test_build(machine: Path, monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(mumble.MumbleError, match="needs its sources"):
        mumble.build()
    touch(machine / "src" / "CMakeLists.txt")
    programs(monkeypatch, "cmake", "gcc")
    bundle = machine / "src" / "build" / mumble.BUNDLE_NAME
    runs = Runs(makes=bundle)
    monkeypatch.setattr(mumble.subprocess, "run", runs)
    assert mumble.build() == bundle
    assert runs[1] == ["cmake", "--build", str(machine / "src" / "build")]

    bundle.unlink()
    monkeypatch.setattr(mumble.subprocess, "run", Runs())
    with pytest.raises(mumble.MumbleError, match="The build made no"):
        mumble.build()
    monkeypatch.setattr(mumble.subprocess, "run", Runs(1, "CMake Error: no compiler\nConfiguring incomplete\n"))
    with pytest.raises(mumble.MumbleError, match="cmake -S failed: Configuring incomplete"):
        mumble.build()
    monkeypatch.setattr(mumble.subprocess, "run", Runs(2))
    with pytest.raises(mumble.MumbleError, match="cmake -S failed: 2"):
        mumble.build()


def test_install(machine: Path, monkeypatch: pytest.MonkeyPatch):
    started: list[list[str]] = []

    def popen(command: list[str], **options: Any) -> None:
        if command[0] == "broken":
            raise FileNotFoundError(2, "No such file")
        started.append(command)
        assert options["start_new_session"]

    monkeypatch.setattr(mumble.subprocess, "Popen", popen)
    bundle = touch(machine / "usr" / "share" / "xtouch-daemon" / mumble.BUNDLE_NAME)
    with pytest.raises(mumble.MumbleError, match="Mumble is not installed"):
        mumble.install()
    programs(monkeypatch, "mumble")
    assert "Reload plugins" in mumble.install()
    assert started == [["mumble", "-m", str(bundle)]]

    # without a bundle, or asked to: built first
    built = machine / "src" / "build" / mumble.BUNDLE_NAME
    monkeypatch.setattr(mumble, "build", lambda: touch(built))
    mumble.install(rebuild=True)
    assert started[-1] == ["mumble", "-m", str(built)]

    monkeypatch.setattr(mumble, "mumble_command", lambda bundle: ["broken"])
    with pytest.raises(mumble.MumbleError, match="Can't start broken"):
        mumble.install()
