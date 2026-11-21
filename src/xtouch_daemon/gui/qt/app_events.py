"""
The one event filter of the whole application. Parts that need events of every widget (the keys and the wheel of the
fields, the menus of texts, the tips) watch the kinds they want through it: each event goes into Python once, not
once per part, and on to the parts that want its kind only. Qt sends a filter of the application every event of
every widget, also while a new theme restyles all of them.
"""

from collections.abc import Iterable

from PyQt6.QtCore import QCoreApplication, QEvent, QObject


class AppEvents(QObject):
    def __init__(self, app: QCoreApplication) -> None:
        # a child of the application: each application (one per zoom) has its own
        super().__init__(app)  # pyright: ignore[reportArgumentType]: PyQt's stub types the parent as Self
        self.wanted: dict[QEvent.Type, list[QObject]] = {}
        """The parts that watch each kind of event, in the order they started."""
        app.installEventFilter(self)  # pyright: ignore[reportArgumentType]

    def watch(self, part: QObject, kinds: Iterable[QEvent.Type]) -> None:
        """`part.eventFilter` gets the events of `kinds` of the whole application, until `unwatch` or its end."""
        for kind in kinds:
            self.wanted.setdefault(kind, []).append(part)
        part.destroyed.connect(lambda: self.unwatch(part))

    def unwatch(self, part: QObject) -> None:
        for parts in self.wanted.values():
            if part in parts:
                parts.remove(part)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is None:
            return False
        parts = self.wanted.get(a1.type())
        if not parts:
            return False
        # the newest first, as Qt asks its filters
        return any(part.eventFilter(a0, a1) for part in reversed(tuple(parts)))  # pyright: ignore[reportArgumentType]


def app_events() -> AppEvents:
    """The filter of the running application."""
    app = QCoreApplication.instance()
    assert app is not None
    found = app.findChild(AppEvents)
    return found if found is not None else AppEvents(app)
