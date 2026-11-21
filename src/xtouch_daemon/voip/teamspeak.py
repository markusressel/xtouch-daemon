"""
The TeamSpeak 3 plugin of the `bridge` VoIP provider (integrations/teamspeak): where its library is, whether
TeamSpeak has it, building it from the sources of a checkout, and installing it.

TeamSpeak loads every library in `~/.ts3client/plugins` when it starts (or with "Reload All" in its settings,
Add-ons), and a plugin has to be enabled there once. Installing copies the library there. A build downloads the
headers of TeamSpeak's plugin SDK the first time (see integrations/teamspeak/CMakeLists.txt). See
docs/guides/teamspeak.md.
"""

import contextlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

LIBRARY_NAME = "xtouch-daemon_linux_amd64.so"
"""The plugin, named as TeamSpeak names the libraries of its plugin packages (TeamSpeak 3 for Linux is 64 bit only)."""
SOURCE_DIR = Path(__file__).resolve().parents[3] / "integrations" / "teamspeak"
"""The sources of the plugin, in a checkout of the repository (not in a release)."""
SHARE_DIRS = (Path("/usr/share/xtouch-daemon"), Path("/usr/local/share/xtouch-daemon"))
"""Where a release installs the plugin."""
INSTALL_DIRS = (Path("/opt/teamspeak3"),)
"""Where TeamSpeak is installed (the Arch package, TeamSpeak's own installer), besides a `teamspeak3` command."""


class TeamSpeakError(Exception):
    """The plugin can't be built or handed to TeamSpeak; the message says why."""


def build_dir(source: Path | None = None) -> Path:
    return (source or SOURCE_DIR) / "build"


def library_candidates(source: Path | None = None) -> list[Path]:
    """Where the plugin may be, in this order: the one of a release, then one built from the sources."""
    return [*(directory / LIBRARY_NAME for directory in SHARE_DIRS), build_dir(source) / LIBRARY_NAME]


def find_library(candidates: list[Path] | None = None) -> Path | None:
    return next((path for path in candidates or library_candidates() if path.is_file()), None)


def config_dir() -> Path:
    """TeamSpeak's settings, with its plugins."""
    return Path.home() / ".ts3client"


def plugin_dir() -> Path:
    return config_dir() / "plugins"


def installed_plugin() -> Path | None:
    """The plugin in TeamSpeak's plugin directory, None if TeamSpeak does not have it."""
    path = plugin_dir() / LIBRARY_NAME
    return path if path.is_file() else None


def teamspeak_installed() -> bool:
    """Whether TeamSpeak 3 is installed: its command, its directory, or its settings (it ran once)."""
    return (
        shutil.which("teamspeak3") is not None
        or any(directory.is_dir() for directory in INSTALL_DIRS)
        or config_dir().is_dir()
    )


def can_build(source: Path | None = None) -> bool:
    """Whether the plugin can be built here: the sources (a checkout), CMake and a C compiler."""
    return (
        ((source or SOURCE_DIR) / "CMakeLists.txt").is_file()
        and shutil.which("cmake") is not None
        and any(shutil.which(compiler) for compiler in ("cc", "gcc", "clang"))
    )


def build(source: Path | None = None) -> Path:
    """Builds the plugin from the sources (see `can_build()`) into their `build` directory, and returns it."""
    source = source or SOURCE_DIR
    if not can_build(source):
        raise TeamSpeakError(f"Building the plugin needs its sources ({source}), cmake and a C compiler")
    target = build_dir(source)
    for command in (
        ["cmake", "-S", str(source), "-B", str(target), "-DCMAKE_BUILD_TYPE=Release"],
        ["cmake", "--build", str(target)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            output = [line for line in (result.stderr or result.stdout).strip().splitlines() if line.strip()]
            raise TeamSpeakError(
                f"{' '.join(command[:2])} failed: {output[-1].strip() if output else result.returncode}"
            )
    library = target / LIBRARY_NAME
    if not library.is_file():
        raise TeamSpeakError(f"The build made no {library}")
    return library


@dataclass(frozen=True)
class Setup:
    """What there is of the plugin on this machine."""

    library: Path | None
    """The plugin to install, if there is one."""
    buildable: bool
    """Whether the plugin can be built here (a checkout with CMake and a C compiler)."""
    installed: Path | None
    """The plugin in TeamSpeak's plugin directory, if TeamSpeak has it."""
    teamspeak: bool
    """Whether TeamSpeak 3 is installed."""

    @property
    def installable(self) -> bool:
        return self.teamspeak and (self.library is not None or self.buildable)


def setup() -> Setup:
    return Setup(
        library=find_library(),
        buildable=can_build(),
        installed=installed_plugin(),
        teamspeak=teamspeak_installed(),
    )


def install(rebuild: bool = False) -> str:
    """
    Copies the plugin (built first if there is none, or with `rebuild`) into TeamSpeak's plugin directory, and says
    what to do in TeamSpeak. The library is replaced as a whole (a new file renamed over the old one), so a TeamSpeak
    that has the old one loaded keeps it until it loads its plugins again.
    """
    library = find_library()
    if library is None or rebuild:
        library = build()
    if not teamspeak_installed():
        raise TeamSpeakError(
            "TeamSpeak 3 is not installed (no teamspeak3 command, no /opt/teamspeak3, no ~/.ts3client)"
        )
    target = plugin_dir()
    new = target / f".{LIBRARY_NAME}.new"
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(library, new)
        new.chmod(0o755)
        new.replace(target / LIBRARY_NAME)
    except OSError as e:
        with contextlib.suppress(OSError):
            new.unlink(missing_ok=True)
        raise TeamSpeakError(f"Can't install the plugin into {target}: {e}") from e
    return (
        f'Installed into {target}. In TeamSpeak: Tools, Options, Add-ons, Plugins: click "Reload All" (or restart '
        'TeamSpeak), and enable "xtouch-daemon" if it is not yet.'
    )
