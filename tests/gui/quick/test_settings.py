"""The page Settings: its sections, the fields of Behavior, absent sections and the aliases."""

from PyQt6.QtCore import Qt

from tests.gui.quick.forms_host import alias_rows, aliases, settings
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.pages.settings import SETTINGS_NAV


def show(ui: Ui, name: str) -> None:
    settings(ui).showSection(name)
    ui.settle()


def test_the_page_lists_its_sections(ui: Ui):
    show(ui, "behavior")
    assert [entry["name"] for entry in settings(ui).entries] == list(SETTINGS_NAV)
    assert ui.shows("settings_page_behavior")
    assert ui.shows("settings_nav_aliases")


def test_another_section_replaces_the_page(ui: Ui):
    show(ui, "behavior")
    ui.click("settings_nav_aliases")
    assert settings(ui).current == "aliases"
    assert ui.shows("settings_page_aliases")
    assert not ui.shows("settings_page_behavior")


def test_a_number_is_written_to_the_document(ui: Ui):
    show(ui, "behavior")
    ui.focus("field_encoder_step")
    ui.item("field_encoder_step").setProperty("text", "")
    ui.type("3")
    assert ui.app.editor.document.get(("behavior", "encoder_step")) == 3


def test_typing_into_one_option_is_one_undo_step(ui: Ui):
    show(ui, "behavior")
    ui.focus("field_max_volume")
    ui.item("field_max_volume").setProperty("text", "")
    ui.type("110")
    assert ui.app.editor.document.get(("behavior", "max_volume")) == 110
    ui.app.editor.undo()
    assert ui.app.editor.document.get(("behavior", "max_volume")) == 120


def test_a_switch_can_be_reset_to_its_default(ui: Ui):
    show(ui, "behavior")
    document = ui.app.editor.document
    settings(ui).reveal(["behavior", "meters"])
    ui.settle()
    ui.click("switch_meters")
    assert document.get(("behavior", "meters")) is False
    ui.click("reset_meters")
    assert document.get(("behavior", "meters")) is None
    assert ui.item("switch_meters").property("checked") is True


def test_the_help_shows_the_default_and_a_link(ui: Ui):
    show(ui, "behavior")
    text = ui.text("help_max_volume")
    assert "DEFAULT" in text
    assert "Learn&nbsp;more" in text


def test_a_value_changed_elsewhere_changes_its_row_in_place(ui: Ui):
    show(ui, "behavior")
    before = ui.item("field_encoder_step")
    ui.app.editor.document.set(("behavior", "encoder_step"), 4)
    ui.app.editor.edited()
    ui.settle()
    assert ui.item("field_encoder_step") is before
    assert ui.text("field_encoder_step") == "4"


def test_an_absent_section_is_added_and_removed(ui: Ui):
    show(ui, "homeassistant")
    document = ui.app.editor.document
    assert ui.shows("add_mqtt")
    ui.click("add_mqtt")
    assert document.has_section("mqtt")
    assert ui.shows("remove_mqtt")
    ui.click("remove_mqtt")
    assert not document.has_section("mqtt")
    assert ui.shows("add_mqtt")


def test_reveal_shows_the_section_of_an_option(ui: Ui):
    settings(ui).reveal(["behavior", "meters"])
    ui.settle()
    assert ui.app.page == "settings"
    assert settings(ui).current == "behavior"


def test_reveal_ignores_unknown_sections(ui: Ui):
    settings(ui).reveal(["nonsense", "x"])
    settings(ui).reveal([])
    assert settings(ui).current == "behavior"


def test_an_alias_is_added_edited_and_removed(ui: Ui):
    show(ui, "aliases")
    ui.click("alias_add")
    key = alias_rows(ui).keys()[-1]
    ui.wait_until(lambda: ui.find(f"alias_name_{key}") is not None)
    ui.focus(f"alias_name_{key}")
    ui.type("Discord")
    ui.focus(f"alias_alias_{key}")
    ui.type("Chat")
    assert ui.app.editor.document.get(("aliases",)).get("Discord") == "Chat"
    ui.click(f"alias_remove_{key}")
    assert key not in alias_rows(ui).keys()  # noqa: SIM118
    assert "Discord" not in ui.app.editor.document.get(("aliases",))


def test_a_name_twice_is_marked(ui: Ui):
    show(ui, "aliases")
    backend = aliases(ui)
    first, second = backend.add(), backend.add()
    backend.setName(first, "Discord")
    backend.setName(second, "Discord")
    ui.settle()
    assert any(
        alias_rows(ui).data(alias_rows(ui).index(at), Qt.ItemDataRole.UserRole + 2)["nameProblem"]
        for at in range(alias_rows(ui).count)
    )
    assert backend.rest
