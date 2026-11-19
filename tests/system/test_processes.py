"""
The processes that run, from /proc.
"""

from pathlib import Path

import pytest

from xtouch_daemon.system.processes import running_processes


def test_running_processes_are_the_names_and_programs_of_proc(tmp_path: Path):
    for pid, comm, cmdline in (
        ("12", "mumble\n", b"/usr/bin/mumble\0--multiple\0"),
        ("13", "Web Content\n", b"/usr/lib/firefox/firefox\0-contentproc\0"),
        # kernel threads have no command line: "oom_reaper" must not match a rule for Steam's "reaper"
        ("14", "oom_reaper\n", b""),
        ("17", "reaper\n", b"/home/me/.local/share/Steam/ubuntu12_32/reaper\0SteamLaunch\0"),
    ):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "comm").write_text(comm)
        (tmp_path / pid / "cmdline").write_bytes(cmdline)
    # gone in the meantime, and no process at all
    (tmp_path / "15").mkdir()
    (tmp_path / "self").mkdir()
    (tmp_path / "16").mkdir()
    (tmp_path / "16" / "comm").write_text("\n")
    (tmp_path / "16" / "cmdline").write_bytes(b"")
    assert running_processes(tmp_path) == {"mumble", "web content", "firefox", "reaper"}


def test_steams_install_scripts_are_no_running_game(tmp_path: Path):
    """After an update Steam runs the install scripts of a game through its reaper, with Install=1."""

    def scan(*commands: bytes) -> frozenset[str]:
        directory = tmp_path / str(len(list(tmp_path.iterdir())))
        directory.mkdir()
        for pid, command in enumerate(commands, start=10):
            (directory / str(pid)).mkdir()
            (directory / str(pid) / "comm").write_text(Path(command.split(b"\0")[0].decode()).name[:15] + "\n")
            (directory / str(pid) / "cmdline").write_bytes(command)
        return running_processes(directory)

    install = b"/s/reaper\0SteamLaunch\0AppId=314650\0Install=1\0--\0/s/proton\0run\0x.exe\0"
    assert scan(install, b"/s/reaper\0SteamLaunch\0Install=1\0") == frozenset()
    # a game, also one with Install=1 among its own arguments, and Install=1 without Steam's reaper
    assert scan(b"/s/reaper\0SteamLaunch\0AppId=1\0--\0/s/game\0Install=1\0") == {"reaper"}
    assert scan(b"/usr/bin/steam\0Install=1\0", b"/s/reaper\0Install=1\0") == {"steam", "reaper"}


@pytest.mark.host
def test_running_processes_of_this_machine_include_this_one():
    assert Path("/proc/self/comm").read_text().strip().lower() in running_processes(Path("/proc"))
