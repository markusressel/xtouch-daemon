"""
Parts bound to entities of Home Assistant in the forms: suggestions of what Home Assistant has (read with a fake, never
over the network), the options of a table of an entity, and the page of `[homeassistant]` with its test.
"""

from typing import Any

import pytest

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.forms_host import settings
from tests.support.quick import Ui
from xtouch_daemon.config.sections import HomeAssistantConfig
from xtouch_daemon.gui.quick.forms import entity_table
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.forms.strips import channel_form
from xtouch_daemon.homeassistant.client import Fetched, HomeAssistantError
from xtouch_daemon.homeassistant.states import EntityState

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
        self.error: str | None = None
        self.reads: list[HomeAssistantConfig] = []

    async def read(self, config: HomeAssistantConfig) -> Fetched:
        self.reads.append(config)
        if self.error is not None:
            raise HomeAssistantError(self.error)
        return Fetched("2026.11.0", ENTITIES)


@pytest.fixture
def home() -> FakeHome:
    return FakeHome()


@pytest.fixture
def ui(make_ui: MakeUi, home: FakeHome) -> Ui:
    ui = make_ui(read_entities=home.read)
    ui.app.editor.add_section("homeassistant")
    for key, value in SECTION.items():
        ui.app.editor.document.set(("homeassistant", key), value)
    ui.app.editor.edited()
    return ui


@pytest.fixture
def form(ui: Ui) -> Form:
    result = channel_form(forms_of(ui.app), "output")
    result.retarget(("channel", "out"))
    result.active = True
    return result


def suggested(form: Form, key: str, line: dict[str, Any] | None = None, text: str = "") -> dict[str, Any]:
    return form.suggestions(key, line or {}, text, "dark")


def test_the_entities_are_suggested_once_home_assistant_is_read(ui: Ui, form: Form, home: FakeHome):
    forms_of(ui.app).wantEntities()
    ui.wait_until(lambda: len(suggested(form, "@entity")["rows"]) == len(ENTITIES))
    values = [row["value"] for row in suggested(form, "@entity")["rows"]]
    assert values == [entity.entity_id for entity in ENTITIES]
    assert [config.url for config in home.reads] == [SECTION["url"]]
    assert [row["value"] for row in suggested(form, "@entity", text="kitchen")["rows"]] == ["light.kitchen"]


def test_without_a_connection_the_list_says_why(ui: Ui, form: Form, home: FakeHome):
    home.error = "can't connect to ws://ha.test: Connection refused"
    forms_of(ui.app).wantEntities()
    ui.wait_until(lambda: "Nothing answers" in forms_of(ui.app).entityHint())
    result = suggested(form, "@entity")
    assert result["rows"] == []
    assert "check the address" in result["empty"]


def test_the_attributes_of_an_entity_are_suggested(ui: Ui, form: Form):
    forms_of(ui.app).wantEntities()
    ui.wait_until(lambda: len(suggested(form, "@entity")["rows"]) > 0)
    assert suggested(form, "@attribute", {})["empty"] == "Pick the entity first"
    values = [row["value"] for row in suggested(form, "@attribute", {"entity": "light.desk"})["rows"]]
    assert "brightness" in values
    assert "unknown" in suggested(form, "@attribute", {"entity": "light.nowhere"})["empty"].lower()


def test_an_unset_number_takes_its_range_from_the_entity(ui: Ui, form: Form):
    forms_of(ui.app).wantEntities()
    ui.wait_until(lambda: len(suggested(form, "@entity")["rows"]) > 0)
    table = {"entity": "number.amp", "service": "number.set_value"}
    assert form.entityStart("encoder", True, {**table, "min": 20, "max": 40}) == 20
    assert form.entityPlaceholder("entity", None, "entity", False, {}) == "e.g. light.desk"
    assert form.entityPlaceholder("entity", None, "service", False, {}) == "default: none"


def test_a_table_of_an_entity_keeps_its_marker(ui: Ui, form: Form):
    context = forms_of(ui.app)
    table = context.entityPut({"entity": "light.desk", "attribute": "brightness"}, "attribute", None, "entity")
    assert table == {"entity": "light.desk"}
    assert context.entityPut(table, "entity", None, "entity") == {"entity": ""}
    assert context.entityPut(table, "step", 5, "entity") == {"entity": "light.desk", "step": 5}


def test_a_number_starts_where_the_domain_starts():
    assert entity_table.start_of("min", {}, False, None) == 0
    assert entity_table.start_of("max", {}, False, None) == 100
    assert entity_table.start_of("min", {"min": 5}, False, None) == 5
    # a range that is none
    assert entity_table.start_of("min", {"min": 9, "max": 3}, False, None) == 0
    assert entity_table.start_of("step", {"min": 0, "max": 100}, False, None) > 0


def test_a_value_binding_knows_that_it_sets_a_value():
    from xtouch_daemon.config.bindings import EntityValueBinding

    assert entity_table.sets_value(EntityValueBinding)
    assert not entity_table.sets_value(None)


# -- the page of [homeassistant] ------------------------------------------------------------------------------------


def test_the_settings_of_home_assistant_can_be_tried(ui: Ui, home: FakeHome):
    settings(ui).showSection("homeassistant")
    ui.settle()
    assert ui.shows("test_homeassistant")
    ui.click("test_homeassistant")
    ui.wait_until(lambda: bool(ui.text("test_result_homeassistant")))
    assert [config.url for config in home.reads][-1] == SECTION["url"]


def test_a_test_that_fails_says_so(ui: Ui, home: FakeHome):
    home.error = "can't connect to ws://ha.test: Connection refused"
    settings(ui).showSection("homeassistant")
    ui.settle()
    ui.click("test_homeassistant")
    ui.wait_until(lambda: "Connection refused" in ui.text("test_result_homeassistant"))
    assert ui.item("test_homeassistant").property("enabled") is True


def test_the_settings_of_home_assistant_are_shown_on_request(ui: Ui):
    forms_of(ui.app).showSettingsOfHomeAssistant()
    ui.settle()
    assert settings(ui).current == "mqtt"


def test_an_unset_option_of_a_table_has_a_placeholder():
    amp = ENTITIES[2]
    assert entity_table.placeholder("service", None, "entity", False, {}, None) == "e.g. light.toggle"
    assert entity_table.placeholder("data", None, "entity", False, {}, None) == "none"
    assert entity_table.placeholder("attribute", None, "entity", False, {}, None) == "default: none: the state"
    assert entity_table.placeholder("entity", None, "service", True, {}, None) == "default: none"
    assert entity_table.placeholder("min", None, "entity", True, {"entity": "number.amp"}, amp) is not None
    assert entity_table.start_of("min", {"entity": "number.amp"}, True, amp) == 10
    assert entity_table.start_of("max", {"entity": "number.amp"}, True, amp) == 60
