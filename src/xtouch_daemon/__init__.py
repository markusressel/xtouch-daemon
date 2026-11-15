"""Use a Behringer X-Touch Extender as a hardware mixer for PipeWire."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("xtouch-daemon")
except PackageNotFoundError:  # pragma: no cover - only without an installed package
    __version__ = "0.0.0"


def installed_version() -> str:
    """
    The version installed now. It differs from `__version__`, the version of the program that runs, after an upgrade
    until the program starts again.
    """
    return version("xtouch-daemon")
