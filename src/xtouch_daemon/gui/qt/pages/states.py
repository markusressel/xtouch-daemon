"""
The page States: the modes, then the other states, with their sources, delays and live values.
"""

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from xtouch_daemon.gui.qt.fields.basics import label


class StatesPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(label("States", "section"))
        layout.addStretch()
