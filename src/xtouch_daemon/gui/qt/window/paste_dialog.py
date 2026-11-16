"""
The question how to paste a copied strip where it could also be inherited: as an `inherit` strip, or a copy.
"""

from PyQt6.QtWidgets import QMessageBox, QWidget

from xtouch_daemon.gui.domain.clipboard import CopiedStrip, Paste

INHERIT_TEXT = "Inherit"
COPY_TEXT = "Copy"


def ask_paste(parent: QWidget, copied: CopiedStrip, place: str) -> Paste | None:
    """How to paste `copied` at `place` (e.g. "strip 3"), None for not at all."""
    box = QMessageBox(QMessageBox.Icon.Question, "Paste strip", f"Paste {copied} at {place}:", parent=parent)
    box.setInformativeText(
        "Inherit: an inherit strip that refers to it, so it changes with it.\n"
        "Copy: all its options, from then on on their own."
    )
    inherit = box.addButton(INHERIT_TEXT, QMessageBox.ButtonRole.AcceptRole)
    copy = box.addButton(COPY_TEXT, QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(inherit)
    box.exec()
    clicked = box.clickedButton()
    if clicked is inherit:
        return Paste.INHERIT
    return Paste.COPY if clicked is copy else None
