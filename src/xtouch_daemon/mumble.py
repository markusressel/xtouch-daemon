"""
The Mumble plugin of the `bridge` VoIP provider (integrations/mumble): where its bundle is, whether Mumble has it,
building it from the sources of a checkout, and handing it to Mumble, which asks the user to install it.

A bundle (`xtouch-daemon.mumble_plugin`) is a zip of the plugin library and a manifest. `mumble <bundle>` shows
Mumble's own installer, which copies the library into Mumble's plugin directory; the plugin still has to be enabled in
Mumble's settings (Plugins) once. See docs/integrations/mumble.md.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

BUNDLE_NAME = "xtouch-daemon.mumble_plugin"
LIBRARY_NAME = "libxtouch-daemon.so"
FLATPAK_ID = "info.mumble.Mumble"
SOURCE_DIR = Path(__file__).resolve().parents[2] / "integrations" / "mumble"
"""The sources of the plugin, in a checkout of the repository (not in a release)."""
SHARE_DIRS = (Path("/usr/share/xtouch-daemon"), Path("/usr/local/share/xtouch-daemon"))
"""Where a release installs the bundle."""
FLATPAK_SYSTEM = Path("/var/lib/flatpak")


class MumbleError(Exception):
    """The plugin can't be built or handed to Mumble; the message says why."""


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def build_dir(source: Path | None = None) -> Path:
    return (source or SOURCE_DIR) / "build"


def bundle_candidates(source: Path | None = None) -> list[Path]:
    """Where a bundle may be, in this order: the one of a release, then one built from the sources."""
    return [*(directory / BUNDLE_NAME for directory in SHARE_DIRS), build_dir(source) / BUNDLE_NAME]


def find_bundle(candidates: list[Path] | None = None) -> Path | None:
    return next((path for path in candidates or bundle_candidates() if path.is_file()), None)


def plugin_dirs() -> list[Path]:
    """The directories Mumble installs plugins into: the one of a native Mumble, then the one of the Flatpak."""
    return [
        _data_home() / "Mumble" / "Mumble" / "Plugins",
        Path.home() / ".var" / "app" / FLATPAK_ID / "data" / "Mumble" / "Mumble" / "Plugins",
    ]


def installed_plugin(directories: list[Path] | None = None) -> Path | None:
    """The plugin library in Mumble's plugin directory, None if Mumble does not have it."""
    return next(
        (
            directory / LIBRARY_NAME
            for directory in directories or plugin_dirs()
            if (directory / LIBRARY_NAME).is_file()
        ),
        None,
    )


def flatpak_installed() -> bool:
    """Whether Mumble is installed as a Flatpak, for all users or for this one."""
    return any((root / "app" / FLATPAK_ID).is_dir() for root in (FLATPAK_SYSTEM, _data_home() / "flatpak"))


def mumble_command(bundle: Path) -> list[str] | None:
    """
    How to open a bundle with Mumble's installer, None without Mumble. `-m`: a Mumble that runs already would take the
    call over (it only comes to the front) instead of installing.
    """
    if shutil.which("mumble"):
        return ["mumble", "-m", str(bundle)]
    if shutil.which("flatpak") and flatpak_installed():
        # the sandbox gets the file
        return ["flatpak", "run", "--file-forwarding", FLATPAK_ID, "-m", "@@", str(bundle), "@@"]
    return None


def can_build(source: Path | None = None) -> bool:
    """Whether the bundle can be built here: the sources (a checkout), CMake and a C compiler."""
    return (
        ((source or SOURCE_DIR) / "CMakeLists.txt").is_file()
        and shutil.which("cmake") is not None
        and any(shutil.which(compiler) for compiler in ("cc", "gcc", "clang"))
    )


def build(source: Path | None = None) -> Path:
    """Builds the bundle from the sources (see `can_build()`) into their `build` directory, and returns it."""
    source = source or SOURCE_DIR
    if not can_build(source):
        raise MumbleError(f"Building the plugin needs its sources ({source}), cmake and a C compiler")
    target = build_dir(source)
    for command in (
        ["cmake", "-S", str(source), "-B", str(target), "-DCMAKE_BUILD_TYPE=Release"],
        ["cmake", "--build", str(target)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip().splitlines()
            raise MumbleError(f"{' '.join(command[:2])} failed: {output[-1] if output else result.returncode}")
    bundle = target / BUNDLE_NAME
    if not bundle.is_file():
        raise MumbleError(f"The build made no {bundle}")
    return bundle


@dataclass(frozen=True)
class Setup:
    """What there is of the plugin on this machine."""

    bundle: Path | None
    """The bundle to install, if there is one."""
    buildable: bool
    """Whether a bundle can be built here (a checkout with CMake and a C compiler)."""
    installed: Path | None
    """The plugin in Mumble's plugin directory, if Mumble has it."""
    mumble: bool
    """Whether Mumble is installed (natively or as a Flatpak)."""

    @property
    def installable(self) -> bool:
        return self.mumble and (self.bundle is not None or self.buildable)


def setup() -> Setup:
    bundle = find_bundle()
    return Setup(
        bundle=bundle,
        buildable=can_build(),
        installed=installed_plugin(),
        mumble=mumble_command(bundle or Path(BUNDLE_NAME)) is not None,
    )


def install(rebuild: bool = False) -> str:
    """
    Opens the bundle with Mumble's installer (built first if there is none, or with `rebuild`), and says what happens
    next. It does not wait for Mumble.
    """
    bundle = find_bundle()
    if bundle is None or rebuild:
        bundle = build()
    command = mumble_command(bundle)
    if command is None:
        raise MumbleError("Mumble is not installed (no mumble command, no Flatpak info.mumble.Mumble)")
    try:
        subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise MumbleError(f"Can't start {command[0]}: {e}") from e
    return (
        f"Mumble asks whether to install {bundle.name}: confirm. Then, in Mumble's Settings, Plugins, click "
        '"Reload plugins" (or restart Mumble) and enable "xtouch-daemon".'
    )
