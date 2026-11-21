"""
Tooltips in the colors of the help: every plain tooltip shows with `code` in a monospace font and the states, channels
and slots it names in their colors (see `help_text`). Its first paragraph is what it is about; the ones after it (how,
"Click for details.") are muted, so the first one reads at a glance.
"""

from PyQt6.QtCore import QEvent, QObject, QRect
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtWidgets import QToolTip, QWidget

from xtouch_daemon.gui.qt.app_events import app_events
from xtouch_daemon.gui.qt.fields.basics import help_text
from xtouch_daemon.gui.qt.theme.style import current_colors


def tip_html(tip: str) -> str:
    """`tip` (plain text, paragraphs split by an empty line) as the rich text of a tooltip."""
    first, *rest = tip.split("\n\n")
    paragraphs = [_lines(first)]
    muted = current_colors().text_muted
    paragraphs += [f'<span style="color: {muted}">{_lines(paragraph)}</span>' for paragraph in rest]
    return "<br><br>".join(paragraphs)


def _lines(paragraph: str) -> str:
    return "<br>".join(help_text(line) for line in paragraph.split("\n"))


class RichTips(QObject):
    """Shows the plain tooltips of the whole application as `tip_html`; HTML ones stay as they are."""

    def __init__(self) -> None:
        super().__init__()
        app_events().watch(self, (QEvent.Type.ToolTip,))

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
        if event is None or event.type() != QEvent.Type.ToolTip or not isinstance(watched, QWidget):
            return False
        tip = watched.toolTip()
        if not tip or tip.lstrip().startswith("<"):
            return False
        assert isinstance(event, QHelpEvent)
        QToolTip.showText(event.globalPos(), tip_html(tip), watched, QRect(), watched.toolTipDuration())
        return True
