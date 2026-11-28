"""
The icons of QML: Material Design icons (qtawesome's mdi6) as `image://icon/<name>`, e.g.
`icon.source: "image://icon/content-save"`. They are drawn white; a control tints them (`icon.color`), so one
picture serves every theme.
"""

import qtawesome as qta
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtQuick import QQuickImageProvider

PROVIDER = "icon"
DEFAULT_SIZE = 24


class IconProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Pixmap)

    def requestPixmap(self, id: str | None, requestedSize: QSize) -> tuple[QPixmap, QSize]:
        name = (id or "").split("?", 1)[0]
        side = max(requestedSize.width(), requestedSize.height())
        side = side if side > 0 else DEFAULT_SIZE
        pixmap = qta.icon(f"mdi6.{name}", color="#ffffff").pixmap(side, side)
        return pixmap, pixmap.size()
