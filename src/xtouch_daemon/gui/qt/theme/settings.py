"""
What the window remembers of its look: the zoom, and the share of the height the preview has.
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


# -- the size of the preview ---------------------------------------------------------------------------------------

_PREVIEW_SHARE_KEY = "preview_share"


def load_preview_share() -> float | None:
    """
    The share of the height the preview had last, next to the editor below it (0..1), or None while it has not been
    dragged (or for a value that is not one).
    """
    value = QSettings().value(_PREVIEW_SHARE_KEY)
    try:
        share = float(value)  # pyright: ignore[reportArgumentType]
    except TypeError, ValueError:
        return None
    return share if 0 < share < 1 else None


def save_preview_share(share: float) -> None:
    QSettings().setValue(_PREVIEW_SHARE_KEY, share)


def zoom_step(zoom: float, steps: int) -> float:
    """The level `steps` levels above (or below) `zoom`, within ZOOM_LEVELS."""
    index = ZOOM_LEVELS.index(zoom) if zoom in ZOOM_LEVELS else ZOOM_LEVELS.index(1.0)
    return ZOOM_LEVELS[max(0, min(len(ZOOM_LEVELS) - 1, index + steps))]


def zoom_text(zoom: float) -> str:
    return f"{round(zoom * 100)} %"
