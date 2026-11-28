"""
The QML engine of the GUI: our style of the controls (`qml/XTouchStyle`, on top of Qt's Basic), our components
(`import XTouch.Controls`), the singleton `Theme` (`import XTouch`) and the icons (`image://icon/<name>`).

`Theme` is a QML singleton (`qml/XTouch/Theme.qml`) over the `Theme` of Python that each engine has as its context
property `xtouchTheme`: PyQt calls the factory of a singleton type of Python for the first engine only.
"""

from pathlib import Path

from PyQt6.QtQml import QQmlApplicationEngine, QQmlEngine
from PyQt6.QtQuickControls2 import QQuickStyle

from xtouch_daemon.gui.quick.icons import PROVIDER, IconProvider
from xtouch_daemon.gui.quick.theme import Theme

QML = Path(__file__).with_name("qml")
"""The QML of the GUI: the style, the components and the window, each a module of its own directory."""
STYLE = "XTouchStyle"
THEME = "xtouchTheme"
"""The context property of an engine with its `Theme`, which `qml/XTouch/Theme.qml` shows to QML."""


def make_engine(theme: Theme | None = None) -> QQmlApplicationEngine:
    """An engine that knows our style, components, theme and icons."""
    QQuickStyle.setStyle(STYLE)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML))
    engine.addImageProvider(PROVIDER, IconProvider())
    theme = theme if theme is not None else Theme()
    theme.setParent(engine)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
    context = engine.rootContext()
    assert context is not None
    context.setContextProperty(THEME, theme)
    return engine


def theme_of(engine: QQmlEngine) -> Theme:
    context = engine.rootContext()
    assert context is not None
    theme = context.contextProperty(THEME)
    assert isinstance(theme, Theme)
    return theme
