"""
The Mumble plugin of the `bridge` VoIP provider (integrations/mumble): where its bundle is, whether Mumble has it,
building it from the sources of a checkout, and installing it.

A bundle (`xtouch-daemon.mumble_plugin`) is a zip of the plugin library and a manifest. Installing copies the library
into Mumble's plugin directory, as Mumble's own installer does; Mumble loads it with "Reload plugins" in its settings
(Plugins), or when it starts, and it has to be enabled there once. Mumble's installer (`mumble <bundle>`) is not used:
with a Mumble that runs, it needs a second instance (`--multiple`), which loads the plugin a second time and crashed
(Mumble 1.5.939). See docs/integrations/mumble.md.
"""

import contextlib
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

BUNDLE_NAME = "xtouch-daemon.mumble_plugin"
LIBRARY_NAME = "libxtouch-daemon.so"
FLATPAK_ID = "info.mumble.Mumble"
SOURCE_DIR = Path(__file__).resolve().parents[3] / "integrations" / "mumble"
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


def target_dir() -> Path | None:
    """The plugin directory of the Mumble that is installed (native first, then the Flatpak), None without Mumble."""
    native, flatpak = plugin_dirs()
    if shutil.which("mumble"):
        return native
    if flatpak_installed():
        return flatpak
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
        mumble=target_dir() is not None,
    )


def install(rebuild: bool = False) -> str:
    """
    Copies the plugin library of the bundle (built first if there is none, or with `rebuild`) into Mumble's plugin
    directory, and says what to do in Mumble. The library is replaced as a whole (a new file renamed over the old
    one), so a Mumble that has the old one loaded keeps it until it reloads its plugins.
    """
    bundle = find_bundle()
    if bundle is None or rebuild:
        bundle = build()
    target = target_dir()
    if target is None:
        raise MumbleError("Mumble is not installed (no mumble command, no Flatpak info.mumble.Mumble)")
    try:
        with zipfile.ZipFile(bundle) as archive:
            library = archive.read(LIBRARY_NAME)
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        raise MumbleError(f"Can't read the plugin from {bundle}: {e}") from e
    new = target / f".{LIBRARY_NAME}.new"
    try:
        target.mkdir(parents=True, exist_ok=True)
        new.write_bytes(library)
        new.chmod(0o644)
        new.replace(target / LIBRARY_NAME)
    except OSError as e:
        with contextlib.suppress(OSError):
            new.unlink(missing_ok=True)
        raise MumbleError(f"Can't install the plugin into {target}: {e}") from e
    return (
        f'Installed into {target}. In Mumble\'s Settings, Plugins: click "Reload plugins" (or restart Mumble), and '
        'enable "xtouch-daemon" if it is not yet.'
    )
