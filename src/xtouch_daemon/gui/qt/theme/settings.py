"""
What the window remembers of its look: the zoom, the shares of the panes of the pages, and where its docks are.
"""

from PyQt6.QtCore import QSettings

ZOOM_LEVELS = (0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
"""The zoom levels of the window, like those of a browser."""
_ZOOM_KEY = "zoom"


def load_zoom() -> float:
    """The zoom level chosen last, 1.0 at first (or for a value that is not one of ZOOM_LEVELS)."""
    value = QSettings().value(_ZOOM_KEY, 1.0)
    try:
        zoom = float(value)  # pyright: ignore[reportArgumentType]
    except TypeError, ValueError:
        return 1.0
    return zoom if zoom in ZOOM_LEVELS else 1.0


def save_zoom(zoom: float) -> None:
    QSettings().setValue(_ZOOM_KEY, zoom)


# -- the panes of the pages ---------------------------------------------------------------------------------------


def _split_key(name: str) -> str:
    return f"split/{name}"


def load_split(name: str) -> float | None:
    """
    The share of the width the left pane of the page `name` had last (0..1), or None while its handle has not been
    dragged (or for a value that is not one).
    """
    value = QSettings().value(_split_key(name))
    try:
        share = float(value)  # pyright: ignore[reportArgumentType]
    except TypeError, ValueError:
        return None
    return share if 0 < share < 1 else None


def save_split(name: str, share: float) -> None:
    QSettings().setValue(_split_key(name), share)


# -- the window ---------------------------------------------------------------------------------------------------

_WINDOW_KEY = "window_state"


def load_window_state() -> bytes | None:
    """Where the docks of the window were (`QMainWindow.saveState()`), None at first."""
    value = QSettings().value(_WINDOW_KEY)
    return bytes(value) if isinstance(value, bytes | bytearray) else None


def save_window_state(state: bytes) -> None:
    QSettings().setValue(_WINDOW_KEY, state)


def zoom_step(zoom: float, steps: int) -> float:
    """The level `steps` levels above (or below) `zoom`, within ZOOM_LEVELS."""
    index = ZOOM_LEVELS.index(zoom) if zoom in ZOOM_LEVELS else ZOOM_LEVELS.index(1.0)
    return ZOOM_LEVELS[max(0, min(len(ZOOM_LEVELS) - 1, index + steps))]


def zoom_text(zoom: float) -> str:
    return f"{round(zoom * 100)} %"
