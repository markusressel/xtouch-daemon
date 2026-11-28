"""
The entities of Home Assistant the window knows (`EntitySource`), read in a thread with the settings of
`[homeassistant]` in the editor, for the fields of entities and the test of the settings.
"""

import asyncio
import threading
import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.gui.domain.entities import (
    EntityCache,
    Fetch,
    Tried,
    entity_suggestions,
    section_config,
    try_home_assistant,
    why_no_entities,
)
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.homeassistant.client import fetch
from xtouch_daemon.homeassistant.states import EntityState
from xtouch_daemon.live.messages import HomeAssistantState, Snapshot


class EntitySource(QObject):
    """
    The entities of Home Assistant the window knows, for the fields of entities: read with the settings of
    `[homeassistant]` in the editor (`settings`, also unsaved ones) when a field wants them (`want()`), in a thread,
    and again with other settings or a minute later. The test of the settings (`test()`) reads them too. `changed`
    tells that they (or why there are none) changed, `tested` the result of a test, `settings_wanted` that a field
    asks for the page of the settings.
    """

    changed = pyqtSignal(arguments=[])
    tested = pyqtSignal(object, arguments=["status"])
    settings_wanted = pyqtSignal(arguments=[])
    _read = pyqtSignal(object, object, bool, arguments=["config", "tried", "test"])

    def __init__(
        self,
        settings: Callable[[], object],
        read: Fetch = fetch,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__()
        self._settings = settings
        self._fetch = read
        self._clock = clock
        self.cache = EntityCache()
        self.live: HomeAssistantState | None = None
        """The daemon's connection to Home Assistant, from its live view."""
        self._read.connect(self._done)

    def config(self) -> HomeAssistantConfig | str | None:
        """The settings in the editor (see `section_config`)."""
        return section_config(self._settings())

    def want(self, again: bool = False) -> None:
        """A field shows: reads the entities if the settings changed or they are old (`again`: in any case)."""
        config = self.config()
        if isinstance(config, HomeAssistantConfig) and self.cache.wants(config, self._clock(), again):
            self._start(config, test=False)
            self.changed.emit()

    def test(self, config: HomeAssistantConfig) -> None:
        """Tries the settings: `tested` has the result; the entities it found are the suggestions then."""
        self._start(config, test=True)

    def _start(self, config: HomeAssistantConfig, test: bool) -> None:
        if not test:
            self.cache.start(config)
        threading.Thread(target=self._run, args=(config, test), name="home assistant", daemon=True).start()

    def _run(self, config: HomeAssistantConfig, test: bool) -> None:
        self._read.emit(config, asyncio.run(try_home_assistant(config, self._fetch)), test)

    def _done(self, config: HomeAssistantConfig, tried: Tried, test: bool) -> None:
        self.cache.done(config, tried, self._clock())
        if test:
            self.tested.emit(tried.status)
        self.changed.emit()

    def show_live(self, snapshot: Snapshot | None) -> None:
        live = snapshot.homeassistant if snapshot is not None else None
        if live != self.live:
            self.live = live
            self.changed.emit()

    @property
    def current(self) -> bool:
        """Whether the entities are of the settings in the editor."""
        config = self.config()
        return isinstance(config, HomeAssistantConfig) and self.cache.config == config

    def suggestions(self) -> tuple[Suggestion, ...]:
        return entity_suggestions(self.cache.entities) if self.current else ()

    def entity(self, entity_id: object) -> EntityState | None:
        return self.cache.entity(entity_id) if self.current else None

    def why(self) -> str:
        """Why there are no suggestions, "" while there are (see `why_no_entities`)."""
        return why_no_entities(self.config(), self.cache, self.live)
