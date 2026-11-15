"""Use a Behringer X-Touch Extender as a hardware mixer for PipeWire."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("xtouch-daemon")
except PackageNotFoundError:  # pragma: no cover - only without an installed package
    __version__ = "0.0.0"
