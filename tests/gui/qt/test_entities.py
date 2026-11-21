"""
Parts bound to entities of Home Assistant in the forms: the mode "An entity", its options with suggestions of what
Home Assistant has (read with a fake, never over the network), presses that call services, LEDs that show entities,
the page of `[homeassistant]` with its test, and the connection of the daemon.
"""

import dataclasses
import tomllib

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit
from pytestqt.qtbot import QtBot

from tests.support.gui import (
    FakeLiveDaemon,
    MakeWindow,
    click,
    plain,
    row,
    show_channel,
    shows,
    snapshot,
    strip_state,
)
from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.gui.qt.fields.binding import ENTITY, PROGRAM, WORDS, BindingField
from xtouch_daemon.gui.qt.fields.entities import EntityList, source_of
from xtouch_daemon.gui.qt.fields.entity_table import EntityTable
from xtouch_daemon.gui.qt.window.main_window import MainWindow
from xtouch_daemon.homeassistant.client import Fetched, HomeAssistantError
from xtouch_daemon.homeassistant.states import EntityState
from xtouch_daemon.live.messages import HomeAssistantState

SECTION = {"url": "http://ha.test:8123", "token": "the-token"}
ENTITIES = (
    EntityState("light.desk", "on", {"friendly_name": "Desk lamp", "brightness": 180}),
    EntityState("light.kitchen", "off", {"friendly_name": "Kitchen"}),
    EntityState("number.amp", "30", {"friendly_name": "Amp", "min": 10, "max": 60}),
    EntityState("sensor.temp", "21.5", {"friendly_name": "Temperature", "unit_of_measurement": "°C"}),
)


class FakeHome:
    """Home Assistant as the window reads it: its entities, or an error; the settings it was read with."""

    def __init__(self) -> None:
        self.entities = ENTITIES
        self.error: str | None = None
        self.reads: list[HomeAssistantConfig] = []

    async def read(self, config: HomeAssistantConfig) -> Fetched:
        self.reads.append(config)
        if self.error is not None:
            raise HomeAssistantError(self.error)
        return Fetched("2026.11.0", self.entities)


@pytest.fixture
def home() -> FakeHome:
    return FakeHome()


@pytest.fixture
def window(make_window: MakeWindow, home: FakeHome) -> MainWindow:
    return make_window(read_entities=home.read)


def with_section(window: MainWindow) -> None:
    window.document.add_section("homeassistant")
    for key, value in SECTION.items():
        window.document.set(("homeassistant", key), value)
    window.editor.edited()


def custom(window: MainWindow) -> None:
    window.show_page("channels")
    window.channels_page.add("custom")


def binding(window: MainWindow, name: str) -> BindingField:
    return row(window, name).binding


def written(window: MainWindow, *path: str) -> object:
    value: object = tomllib.loads(window.document.render())
    for key in path:
        assert isinstance(value, dict)
        value = value.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return value


def entity_table(field: BindingField) -> EntityTable:
    assert field.entity is not None
    return field.entity


def suggestions(qtbot: QtBot, edit: QLineEdit, found: EntityList | None) -> list[str]:
    """The lines of the list under `edit`, once it is open."""
    assert found is not None
    edit.setFocus()
    found.open(typed=bool(edit.text()))
    qtbot.waitUntil(lambda: found.is_open)
    return [found.items.item(index).text() for index in range(found.items.rowCount())]  # pyright: ignore[reportOptionalMemberAccess]


def test_a_fader_bound_to_an_entity_suggests_the_entities(qtbot: QtBot, window: MainWindow, home: FakeHome):
    with_section(window)
    custom(window)
    field = binding(window, "fader")
    assert [action.text() for action in field.menu.actions() if action.isVisible()] == [
        "Home Assistant",
        "An entity",
        "A program",
    ]
    field.actions_[ENTITY].trigger()
    assert window.document.get(("channel", "custom", "fader")) == {"entity": ""}
    assert field.bind.text() == "An entity"
    table = entity_table(field)
    assert shows(table, window)
    assert not shows(field.program, window)
    # a fader has no push
    assert list(table.rows) == ["entity", "attribute", "min", "max", "step", "format", "service", "data"]
    # the entities, read when the options showed
    qtbot.waitUntil(lambda: len(home.reads) == 1)
    source = source_of(field)
    assert source is not None
    qtbot.waitUntil(lambda: source.cache.reading is None)
    entity = table.rows["entity"].line
    assert suggestions(qtbot, entity, table.entity_list) == ["light.desk", "light.kitchen", "number.amp", "sensor.temp"]
    # typing narrows them down, by the id or the name; Enter picks the first one
    qtbot.keyClicks(entity, "lamp")
    assert table.entity_list is not None
    assert [table.entity_list.items.item(i).text() for i in range(table.entity_list.items.rowCount())] == ["light.desk"]  # pyright: ignore[reportOptionalMemberAccess]
    qtbot.keyClick(entity, Qt.Key.Key_Return)
    assert not table.entity_list.is_open
    assert entity.text() == "light.desk"
    assert written(window, "channel", "custom", "fader") == {"entity": "light.desk"}
    # what the unset options do, by the domain
    assert table.rows["attribute"].line.placeholderText() == "default: brightness, of a light"
    assert table.rows["max"].spin.specialValueText() == "default: 255, of a light"
    assert table.rows["service"].line.placeholderText() == "default: light.turn_on, of a light"
    assert table.rows["step"].spin.specialValueText() == "default: behavior.encoder_step % of the range"
    # the attributes of the entity
    attribute = table.rows["attribute"].line
    assert suggestions(qtbot, attribute, table.attribute_list) == ["brightness"]
    assert window.document.validate().at("channel", "custom") == []

    # another entity: a number tells its own range
    entity.setFocus()
    entity.selectAll()
    qtbot.keyClicks(entity, "number.amp")
    assert table.rows["max"].spin.specialValueText() == "default: 60, the entity's max"
    # a number set starts in that range
    table.rows["max"].spin.stepBy(1)
    assert window.document.get(("channel", "custom", "fader"))["max"] == pytest.approx(60.0, abs=1)

    # back to not bound, and to the entity again: the options it had
    field.actions_[WORDS].trigger()
    assert window.document.get(("channel", "custom", "fader")) is None
    field.actions_[ENTITY].trigger()
    assert window.document.get(("channel", "custom", "fader"))["entity"] == "number.amp"
    field.actions_[PROGRAM].trigger()
    assert window.document.get(("channel", "custom", "fader")) == {}
    assert not shows(table, window)


def test_a_problem_of_an_entity_shows_under_its_option(qtbot: QtBot, window: MainWindow):
    with_section(window)
    custom(window)
    field = binding(window, "fader")
    field.actions_[ENTITY].trigger()
    table = entity_table(field)
    qtbot.keyClicks(table.rows["entity"].line, "sensor.temp")
    window.editor.edited()
    field = binding(window, "fader")
    table = entity_table(field)
    # nothing sets a sensor by itself
    assert table.rows["service"].error.text().startswith("Nothing sets the state of a sensor entity by itself")
    assert row(window, "fader").error.isHidden()
    assert table.rows["service"].line.placeholderText().startswith("default: none: set one")
    service = table.rows["service"].line
    qtbot.keyClicks(service, "script.set_level")
    data = table.rows["data"].line
    # data typed as an inline table
    qtbot.keyClicks(data, '{ level = "{value}" }')
    assert written(window, "channel", "custom", "fader") == {
        "entity": "sensor.temp",
        "service": "script.set_level",
        "data": {"level": "{value}"},
    }
    assert window.document.validate().at("channel", "custom") == []
    # loaded again, the data shows as typed
    row(window, "fader").load()
    assert entity_table(binding(window, "fader")).rows["data"].line.text() == '{level = "{value}"}'
    # no table: the text goes to the file, its problem says so
    data = entity_table(binding(window, "fader")).rows["data"].line
    data.selectAll()
    qtbot.keyClicks(data, "{ level = ")
    assert window.document.get(("channel", "custom", "fader"))["data"] == "{ level ="
    window.editor.edited()
    assert entity_table(binding(window, "fader")).rows["data"].error.text() != ""


def test_without_the_section_a_field_of_an_entity_says_why_it_suggests_nothing(
    qtbot: QtBot, window: MainWindow, home: FakeHome
):
    custom(window)
    field = binding(window, "lcd")
    field.actions_[ENTITY].trigger()
    table = entity_table(field)
    # an lcd shows the state, or an attribute
    assert list(table.rows) == ["entity", "attribute"]
    assert table.rows["attribute"].line.placeholderText() == "default: none: the state"
    assert shows(table.hint, window)
    assert plain(table.hint.text.text()).startswith("No suggestions: add [homeassistant]")
    lines = suggestions(qtbot, table.rows["entity"].line, table.entity_list)
    assert lines == ["No suggestions: add [homeassistant] with the address of Home Assistant and a token."]
    assert home.reads == []
    # typing works anyway
    qtbot.keyClicks(table.rows["entity"].line, "sensor.cpu")
    assert written(window, "channel", "custom", "lcd") == {"entity": "sensor.cpu"}
    assert suggestions(qtbot, table.rows["attribute"].line, table.attribute_list) == [lines[0]]
    # the button opens the settings
    click(qtbot, table.hint.settings)
    assert window.settings.isVisible()
    assert window.homeassistant_page.isVisible()


def test_an_unreachable_home_assistant_says_what_to_check(qtbot: QtBot, window: MainWindow, home: FakeHome):
    home.error = "can't connect to ws://ha.test:8123/api/websocket: Connection refused"
    with_section(window)
    custom(window)
    field = binding(window, "meter")
    field.actions_[ENTITY].trigger()
    table = entity_table(field)
    assert list(table.rows) == ["entity", "attribute", "min", "max"]
    qtbot.waitUntil(lambda: "Nothing answers" in table.hint.text.text())
    assert shows(table.hint, window)
    # the daemon reaches it with its token
    source = source_of(field)
    assert source is not None
    live = HomeAssistantState("http://ha.test:8123", True, True, None, 42, 0, "2026.11.0")
    source.show_live(dataclasses.replace(snapshot(window, strip_state()), homeassistant=live))
    assert "The daemon is connected, with 42 entities" in plain(table.hint.text.text())
    # it works again: read anew when asked again
    home.error = None
    source.want(again=True)
    qtbot.waitUntil(lambda: table.hint.isHidden())
    assert len(source.suggestions()) == len(ENTITIES)


def test_the_suggestions_are_kept_with_the_keyboard(qtbot: QtBot, window: MainWindow):
    with_section(window)
    custom(window)
    field = binding(window, "color")
    field.actions_[ENTITY].trigger()
    table = entity_table(field)
    source = source_of(field)
    assert source is not None
    qtbot.waitUntil(lambda: bool(source.suggestions()))
    edit = table.rows["entity"].line
    found = table.entity_list
    assert found is not None
    # the focus opens the list, all of it
    edit.setFocus()
    qtbot.waitUntil(lambda: found.is_open)
    assert found.view is not None
    assert not found.view.currentIndex().isValid()
    # Down, Down, Up: the second line... the first; Enter picks it
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    qtbot.keyClick(edit, Qt.Key.Key_Up)
    assert found.view.currentIndex().row() == 1
    qtbot.keyClick(edit, Qt.Key.Key_Enter)
    assert written(window, "channel", "custom", "color") == {"entity": "light.kitchen"}
    assert QApplication.focusWidget() is edit
    # opened again: the entity it has is the current one
    qtbot.keyClick(edit, Qt.Key.Key_Down)
    assert found.is_open
    assert found.view.currentIndex().data() == "light.kitchen"
    # Tab closes it; a click picks
    qtbot.keyClick(edit, Qt.Key.Key_Tab)
    assert not found.is_open
    found.open()
    index = found.items.index(2, 0)
    found.view.clicked.emit(index)
    assert written(window, "channel", "custom", "color") == {"entity": "number.amp"}
    # Enter without a current line closes it; nothing is typed then
    found.open()
    found.view.setCurrentIndex(found.items.index(-1, 0))
    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert not found.is_open
    # a typed text nobody has
    edit.selectAll()
    qtbot.keyClicks(edit, "zzz")
    assert [found.items.item(i).text() for i in range(found.items.rowCount())] == ["Nothing known matches 'zzz'"]  # pyright: ignore[reportOptionalMemberAccess]
    # the list goes with the focus
    edit.setFocus()
    assert found.is_open
    edit.clearFocus()
    qtbot.waitUntil(lambda: not found.is_open)


def test_a_press_calls_a_service_and_an_led_shows_an_entity(qtbot: QtBot, window: MainWindow):
    with_section(window)
    custom(window)
    buttons = row(window, "select").buttons
    press = buttons.combos["press"]
    items = [press.itemText(index) for index in range(press.count())]
    assert items[-1] == "service:"
    led = buttons.combos["led"]
    assert led.itemText(led.count() - 1) == "entity:"
    service = buttons.tables["press"]
    assert not shows(service, window)
    press.setEditText("service: light.toggle")
    assert written(window, "channel", "custom", "select") == {"press": {"service": "light.toggle"}}
    service = row(window, "select").buttons.tables["press"]
    assert shows(service, window)
    assert list(service.rows) == ["service", "entity", "data"]
    assert service.rows["service"].line.text() == "light.toggle"
    qtbot.keyClicks(service.rows["entity"].line, "light.desk")
    qtbot.keyClicks(service.rows["data"].line, "{ brightness_pct = 50 }")
    assert written(window, "channel", "custom", "select") == {
        "press": {"service": "light.toggle", "entity": "light.desk", "data": {"brightness_pct": 50}}
    }
    buttons = row(window, "select").buttons
    assert buttons.combos["press"].currentText() == "service: light.toggle"
    assert "Calls the service of Home Assistant" in plain(buttons.meaning.text())
    # another service typed: the entity and the data stay
    buttons.combos["press"].setEditText("service: light.turn_on")
    assert written(window, "channel", "custom", "select") == {
        "press": {"service": "light.turn_on", "entity": "light.desk", "data": {"brightness_pct": 50}}
    }
    # the service changed below: the list says it
    buttons = row(window, "select").buttons
    service = buttons.tables["press"]
    service.rows["service"].line.selectAll()
    qtbot.keyClicks(service.rows["service"].line, "light.toggle")
    assert buttons.combos["press"].currentText() == "service: light.toggle"

    # the LED: an entity, with its attribute
    buttons.combos["led"].setEditText("entity:")
    entity = row(window, "select").buttons.tables["led"]
    assert shows(entity, window)
    qtbot.keyClicks(entity.rows["entity"].line, "light.desk")
    assert written(window, "channel", "custom", "select")["led"] == {"entity": "light.desk"}  # pyright: ignore[reportIndexIssue, reportOptionalSubscript]
    assert row(window, "select").buttons.combos["led"].currentText() == "entity: light.desk"
    # back to a word: the table goes
    buttons = row(window, "select").buttons
    buttons.combos["press"].setEditText("")
    assert not shows(buttons.tables["press"], window)


def test_a_press_of_the_controls_calls_a_service(qtbot: QtBot, window: MainWindow):
    window.document.set(("controls", "1"), {"rec": {"service": "light.toggle", "entity": "light.desk"}})
    window.editor.edited()
    window.slots_page.select_slot(1)
    entry = window.slots_page.slot_controls.boxes[0]
    buttons = entry.rows["rec"].buttons
    assert buttons.combos["press"].currentText() == "service: light.toggle"
    table = buttons.tables["press"]
    assert table.rows["entity"].line.text() == "light.desk"
    # the LED shows what the press does
    assert buttons.combos["led"].placeholderText() == "What the press does"
    table.rows["entity"].line.selectAll()
    qtbot.keyClicks(table.rows["entity"].line, "light.kitchen")
    # the press alone: the short form
    assert window.document.get(("controls", "1", "rec")) == {"service": "light.toggle", "entity": "light.kitchen"}


def test_the_settings_of_home_assistant_are_tested(qtbot: QtBot, window: MainWindow, home: FakeHome):
    window.show_page("homeassistant")
    page = window.homeassistant_page
    assert not shows(page.box, page)
    window.editor.add_section("homeassistant")
    box = page.box
    assert box.live_pill.text() == "unknown"
    # no address, no token
    click(qtbot, box.test_button)
    assert box.test_result.text() == "Fix the problems of the settings first."
    for key, value in SECTION.items():
        window.document.set(("homeassistant", key), value)
    click(qtbot, box.test_button)
    assert not box.test_button.isEnabled()
    qtbot.waitUntil(lambda: box.test_result.text().startswith("Connected"))
    assert box.test_result.text() == "Connected to Home Assistant 2026.11.0 at http://ha.test:8123: 4 entities."
    assert box.test_button.isEnabled()
    # the entities it found are the suggestions
    assert len(window.entity_source.suggestions()) == len(ENTITIES)

    home.error = "Home Assistant refused the token (Invalid access token or password)"
    click(qtbot, box.test_button)
    qtbot.waitUntil(lambda: "refused the token" in box.test_result.text())
    assert plain(box.test_hint.text()).startswith("Home Assistant does not take the token.")
    assert window.entity_source.suggestions() == ()

    # a result after the section went has nowhere to go
    window.editor.remove_section("homeassistant")
    window.entity_source.tested.emit(None)
    assert page.box.test_result.isHidden()


def test_the_connection_of_the_daemon_shows_on_the_page_and_in_the_connections(
    qtbot: QtBot, make_window: MakeWindow, live_daemon: FakeLiveDaemon, home: FakeHome
):
    window = make_window(live_socket=live_daemon.path, read_entities=home.read)
    qtbot.waitUntil(lambda: bool(live_daemon.clients))
    with_section(window)
    window.show_page("homeassistant")
    page = window.homeassistant_page
    live_daemon.send(snapshot(window, strip_state()))
    qtbot.waitUntil(lambda: page.box.live_pill.text() == "not in use")
    state = HomeAssistantState("http://ha.test:8123", False, False, "Home Assistant refused the token (Invalid)", 0, 2)
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), homeassistant=state))
    qtbot.waitUntil(lambda: page.box.live_pill.text() == "bad token")
    assert "Create a long-lived access token" in plain(page.box.live_detail.text())
    found = [connection.name for connection in window.service_controls.connections]
    assert "Home Assistant API" in found
    state = dataclasses.replace(state, connected=True, synced=True, error=None, entities=7, version="2026.11.0")
    live_daemon.send(dataclasses.replace(snapshot(window, strip_state()), homeassistant=state))
    qtbot.waitUntil(lambda: page.box.live_pill.text() == "connected")
    assert window.entity_source.live == state


def test_demos_show_the_entities(window: MainWindow):
    window.document.set(
        ("channel", "lamp"),
        {"type": "custom", "fader": {"entity": "light.desk"}, "lcd": {"entity": "sensor.temp"}},
    )
    window.editor.edited()
    show_channel(window, "lamp")
    assert window.document.get(("channel", "lamp", "fader")) == {"entity": "light.desk"}
    assert binding(window, "fader").mode == ENTITY
    assert binding(window, "lcd").mode == ENTITY
    assert binding(window, "lcd").word() is None
