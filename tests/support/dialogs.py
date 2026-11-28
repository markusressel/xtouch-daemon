"""The dialogs of the window in Qt Quick for the tests: they answer at once and record what they were asked."""

from collections.abc import Sequence

from xtouch_daemon.gui.quick.window.dialogs import DISCARD, Button


class FakeDialogs:
    """Answers the questions and notes of the window (see `window/dialogs.py`), and records them."""

    def __init__(self) -> None:
        self.answer = DISCARD
        """The id of the button every question is answered with; one that has no such button gets its Esc."""
        self.pick: str | None = None
        """The id of the button of the next questions, before `answer` (e.g. `reload`)."""
        self.shown: list[str] = []
        """The texts of the questions and notes, in order."""
        self.titles: list[str] = []

    def ask(self, title: str, text: str, buttons: Sequence[Button]) -> str:
        self.titles.append(title)
        self.shown.append(text)
        ids = [button.id for button in buttons]
        for wanted in (self.pick, self.answer):
            if wanted in ids:
                return wanted
        return next(button.id for button in buttons if button.role == "reject")

    def tell(self, title: str, text: str) -> None:
        self.titles.append(title)
        self.shown.append(text)
