"""
The release package, installed into the temporary directory of a test.
"""

from pathlib import Path

from xtouch_daemon.system import systemd


def install_package(contains_this_program: bool = True) -> None:
    """Installs the unit of the release package, and makes it the one this program comes from."""
    systemd.PACKAGED_UNIT.parent.mkdir(parents=True, exist_ok=True)
    systemd.PACKAGED_UNIT.write_text(systemd.unit_file("/usr/bin/xtouch-daemon"), encoding="utf-8")
    if contains_this_program:
        # the directory of the installed packages
        systemd.PACKAGE_ROOT = Path(systemd.xtouch_daemon.__file__).resolve().parent.parent
