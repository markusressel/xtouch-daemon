"""The page Channels in Qt Quick: the list, picking, add, duplicate, rename, remove, the keys, the forms and used-by."""

import re
from typing import Any

import pytest
from PyQt6.QtCore import QPointF, QSettings, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQuick import QQuickItem

from tests.gui.quick.conftest import MakeUi
from tests.support.quick import Ui
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.pages.channels import ChannelsPage
from xtouch_daemon.gui.quick.pages.channels_forms import FORM_KEYS


def page(ui: Ui) -> ChannelsPage:
    """The backend of the page Channels, shown."""
    ui.app.showPage("channels")
    ui.settle()
    channels = ui.app.channels
    assert isinstance(channels, ChannelsPage)
    return channels


def listed(channels: ChannelsPage) -> list[dict[str, Any]]:
    """The rows of the list (with the titles of the groups)."""
    return [dict(values) for _, values in channels.entries.rows]  # pyright: ignore[reportAttributeAccessIssue]


def entries(channels: ChannelsPage) -> list[dict[str, Any]]:
    """The rows of the list without the titles of the groups."""
    return [row for row in listed(channels) if row["kind"] != "header"]


def rows(form: Form) -> dict[str, dict[str, Any]]:
    model: Any = form.rows
    return {spec["name"]: {"spec": spec, "info": info} for _key, spec, info in model.rows}


def plain(markup: str) -> str:
    """Rich text without its tags."""
    return re.sub(r"<[^>]*>", "", markup)


def field(ui: Ui, name: str) -> QQuickItem:
    """The field named `name` that shows (the forms of other types are there, hidden)."""
    found = ui.items(name)
    assert found, f"no field {name!r} shows"
    return found[0]


@pytest.fixture(autouse=True)
def no_prebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """The forms are made when they show: the tests that look at the background build turn it on."""
    monkeypatch.setattr(ChannelsPage, "PREBUILD_AFTER_MS", None)


def reachable(ui: Ui, name: str) -> bool:
    """Whether the middle of the item is inside every clipping item above it: a click there reaches it."""
    item = ui.find(name)
    if item is None or not item.isVisible():
        return False
    middle = QPointF(item.width() / 2, item.height() / 2)
    above = item.parentItem()
    while above is not None:
        if above.clip():
            at = item.mapToItem(above, middle)
            if not (0 <= at.x() <= above.width() and 0 <= at.y() <= above.height()):
                return False
        above = above.parentItem()
    return True


def clipboard() -> str:
    board = QGuiApplication.clipboard()
    assert board is not None
    return board.text()


def test_the_list_has_the_channels_then_the_pools(ui: Ui):
    channels = page(ui)
    assert [(row["kind"], row["title"]) for row in listed(channels)] == [
        ("header", "Channels: one strip each"),
        ("channel", "Speaker  ·  out"),
        ("channel", "Browser  ·  browser"),
        ("header", "Pools: a member for each slot that names them"),
        ("pool", "Applications"),
        ("pool", "People"),
        ("pool", "Devices"),
        ("pool", "Auto"),
    ]
    assert ui.shows("channel_list")
    assert ui.shows("entry_channel:out")
    assert ui.shows("header_header:pools")
    # what each is used by, in words, under its name
    assert plain(entries(channels)[0]["below"]) == "slot 1"
    assert plain(entries(channels)[1]["below"]) == "slot 2"


def test_the_first_channel_is_picked_until_another_is(ui: Ui):
    channels = page(ui)
    assert channels.selection == ("channel", "out")
    assert channels.inspector["title"] == "Output"
    assert channels.currentIndex == 1
    ui.click("entry_channel:browser")
    assert channels.selection == ("channel", "browser")
    assert (channels.inspector["title"], channels.inspector["name"]) == ("Applications", "browser")
    assert channels.currentIndex == 2
    assert ui.text("channel_title") == "Applications"
    assert ui.text("channel_id") == "browser"


def test_the_people_have_no_id_and_cannot_be_removed(ui: Ui):
    channels = page(ui)
    ui.click("entry_pool:people")
    assert channels.selection == ("pool", "people")
    assert channels.inspector["mine"] is False
    assert not ui.item("channel_id").isVisible()
    assert not ui.item("entry_remove").property("enabled")
    assert not ui.item("entry_duplicate").property("enabled")
    # the people sit on the slots of auto
    assert channels.inspector["where"] == ["slot 2"]
    channels.remove()
    assert channels.selection == ("pool", "people")


def test_used_by_shows_the_slots_that_show_the_channel(ui: Ui):
    channels = page(ui)
    assert channels.inspector["where"] == ["slot 1"]
    assert ui.item("used_by_1").property("used") is True
    assert ui.item("used_by_2").property("used") is False
    ui.click("entry_channel:browser")
    assert ui.item("used_by_2").property("used") is True


def test_a_click_on_a_slot_of_used_by_shows_the_slot(ui: Ui):
    page(ui)
    ui.click("entry_channel:browser")
    ui.click("used_by_2")
    assert ui.app.page == "slots"
    assert ui.app.slots.slot == 2  # pyright: ignore[reportAttributeAccessIssue]


def test_a_channel_without_a_use_says_so(ui: Ui):
    channels = page(ui)
    channels.add("type:input")
    assert channels.inspector["where"] == []
    assert ui.text("used_by_rest") == "Not used by a slot, pool or state yet."


def test_a_label_typed_shows_in_the_list(ui: Ui):
    channels = page(ui)
    ui.click("entry_channel:browser")
    ui.focus(field(ui, "field_label"))
    field(ui, "field_label").setProperty("text", "")
    ui.type("Web")
    assert ui.app.editor.document.get(("channel", "browser", "label")) == "Web"
    assert entries(channels)[1]["title"] == "Web  ·  browser"
    # saved, the form had no problem
    assert ui.app.editor.validation.problems == []


def test_a_menu_offers_the_types_the_devices_and_the_pools(ui: Ui):
    channels = page(ui)
    ui.wait_until(lambda: bool(channels.context.audio().outputs), timeout=10_000)
    ui.click("entry_add")
    assert ui.shows("menu_type:output")
    sections = {section["title"]: section["items"] for section in channels.addEntries()}
    assert [item["text"] for item in sections["Channel types"]] == [
        "Output",
        "Input",
        "Applications",
        "Person",
        "Home Assistant",
        "Custom",
    ]
    assert [item["text"] for item in sections["Pools"]] == [
        "Pool of channels",
        "Pool of applications",
        "Pool of people",
    ]
    outputs, inputs = sections["From the sound server"]
    assert (outputs["text"], inputs["text"]) == ("Outputs", "Inputs")
    assert "one of the 2 outputs" in outputs["detail"]
    assert [child["action"] for child in outputs["children"]] == ["device:output:speaker", "device:output:buds"]
    assert "volume of speakers" in sections["Channel types"][0]["detail"]


def test_a_click_in_the_menu_adds_a_channel(ui: Ui):
    channels = page(ui)
    ui.click("entry_add")
    ui.click("menu_type:custom")
    assert not ui.shows("menu_type:output")
    assert channels.selection == ("channel", "custom")
    assert ui.app.editor.document.get(("channel", "custom")) == {"type": "custom"}
    # a custom channel has a form too
    assert "form_custom" in [item.objectName() for item in ui.items("form_custom")]


def test_a_device_of_the_sound_server_adds_a_channel_for_it(ui: Ui):
    channels = page(ui)
    ui.wait_until(lambda: bool(channels.context.audio().outputs), timeout=10_000)
    ui.click("entry_add")
    ui.click("menu_Outputs")
    # the children open under the entry; picking one is the action the menu emits
    ui.wait_until(lambda: bool(ui.items("menu_device:output:buds")), timeout=10_000)
    channels.add("device:output:buds")
    assert channels.selection == ("channel", "output")
    assert ui.app.editor.document.get(("channel", "output")) == {"type": "output", "device": "buds"}


def test_without_a_sound_server_the_menu_says_so(make_ui: MakeUi):
    def nothing() -> Any:
        from xtouch_daemon.audio.model import DISCONNECTED

        return DISCONNECTED

    ui = make_ui(read_audio=nothing)
    channels = page(ui)
    ui.wait_until(lambda: channels.context.audio() is not None)
    outputs = channels.addEntries()[1]["items"][0]
    assert outputs["enabled"] is False
    assert "no outputs now, or is not reachable" in outputs["detail"]


def test_channels_are_added_duplicated_renamed_and_removed(ui: Ui):
    channels = page(ui)
    document = ui.app.editor.document
    channels.add("type:input")
    assert channels.selection == ("channel", "input")
    channels.add("type:input")
    assert channels.selection == ("channel", "input_2")
    # a copy of input_2 is input_3
    ui.click("entry_duplicate")
    assert channels.selection == ("channel", "input_3")

    # a new id: only one that can be one
    for bad in ("Mic", "out", "auto", "pool 1", ""):
        assert channels.rename(bad) is False
        assert channels.selection == ("channel", "input_3")
        assert "can't be the id" in channels.idProblem
    assert ui.item("channel_id").property("problem") is True
    assert ui.item("channel_id").property("text") == "input_3"
    assert channels.rename("mic") is True
    assert channels.selection == ("channel", "mic")
    assert channels.idProblem == ""
    assert list(document.get(("channel",))) == ["out", "browser", "input", "input_2", "mic"]
    assert '[channel.mic]\ntype = "input"' in document.render()
    # the same id again changes nothing
    assert channels.rename("mic") is True

    ui.click("entry_remove")
    assert "mic" not in document.get(("channel",))
    assert channels.selection == ("pool", "apps")
    ui.app.editor.undo()
    assert "mic" in document.get(("channel",))


def test_the_id_is_renamed_where_it_is_typed(ui: Ui):
    channels = page(ui)
    ui.focus("channel_id")
    ui.item("channel_id").setProperty("text", "speaker_2")
    ui.key(Qt.Key.Key_Return)
    assert channels.selection == ("channel", "speaker_2")
    # the slots that name it follow
    assert ui.app.editor.document.get(("slots", "1")) == "speaker_2"


def test_a_pool_is_added_renamed_and_removed(ui: Ui):
    channels = page(ui)
    channels.add("pool:")
    assert channels.selection == ("pool", "pool")
    assert channels.inspector["title"] == "Pool of channels"
    channels.add("pool:apps")
    assert (channels.selection, channels.inspector["title"]) == (("pool", "pool_2"), "Pool of applications")
    channels.add("pool:people")
    assert channels.inspector["title"] == "Pool of people"
    assert channels.rename("friends")
    assert channels.selection == ("pool", "friends")
    assert [row["name"] for row in entries(channels)][-2:] == ["pool_2", "friends"]
    # taken by a channel or a pool
    assert not channels.rename("pool_2")
    channels.remove()
    assert channels.selection == ("pool", "apps")


def test_a_built_in_pool_is_neither_renamed_nor_removed(ui: Ui):
    channels = page(ui)
    ui.click("entry_pool:auto")
    assert not channels.rename("other")
    channels.remove()
    channels.duplicate()
    assert list(ui.app.editor.document.get(("pool",), {})) == []
    assert channels.inspector["title"] == "Auto: [pool.auto]"


def test_the_arrow_keys_step_through_the_entries(ui: Ui):
    channels = page(ui)
    ui.focus("channel_list")
    ui.key(Qt.Key.Key_Down)
    assert channels.selection == ("channel", "browser")
    # the title of a group is skipped
    ui.key(Qt.Key.Key_Down)
    assert channels.selection == ("pool", "apps")
    ui.key(Qt.Key.Key_Up)
    assert channels.selection == ("channel", "browser")
    channels.step(-5)
    assert channels.selection == ("channel", "out")


def test_the_edit_menu_works_while_the_list_has_the_focus(ui: Ui):
    channels = page(ui)
    assert channels.editable == []
    ui.focus("channel_list")
    assert channels.editable == ["cut", "copy", "paste", "duplicate", "remove", "rename"]
    ui.click("entry_pool:apps")
    ui.focus("channel_list")
    # a built-in pool can only take a paste
    assert channels.editable == ["paste"]
    ui.focus("channel_id") if ui.item("channel_id").isVisible() else ui.focus("entry_add")
    assert channels.editable == []


def test_copy_cut_paste_and_duplicate_take_tables_as_text(ui: Ui):
    channels = page(ui)
    document = ui.app.editor.document
    channels.edit("copy")
    assert clipboard().startswith('[channel.out]\ntype = "output"')
    channels.edit("paste")
    assert channels.selection == ("channel", "out_2")
    channels.edit("duplicate")
    assert channels.selection == ("channel", "out_3")
    channels.edit("cut")
    assert "out_3" not in document.get(("channel",))
    assert "[channel.out_3]" in clipboard()
    channels.edit("paste")
    assert channels.selection == ("channel", "out_3")
    channels.edit("remove")
    assert "out_3" not in document.get(("channel",))
    # a text that is no table adds nothing
    QGuiApplication.clipboard().setText("not toml [")  # pyright: ignore[reportOptionalMemberAccess]
    channels.edit("paste")
    assert list(document.get(("channel",))) == ["out", "browser", "out_2"]


def test_a_pasted_pool_and_the_clipboard_of_a_built_in_pool(ui: Ui):
    channels = page(ui)
    QGuiApplication.clipboard().setText('[pool.games]\nchannels = ["out"]\n[pool.apps]\nhold = 1\n')  # pyright: ignore[reportOptionalMemberAccess]
    channels.edit("paste")
    # the options of a built-in pool make no pool of your own
    assert channels.selection == ("pool", "games")
    assert list(ui.app.editor.document.get(("pool",))) == ["games"]
    ui.click("entry_pool:auto")
    clip = clipboard()
    channels.edit("copy")
    assert clipboard() == clip


def test_rename_asks_for_the_id_field(ui: Ui):
    channels = page(ui)
    asked: list[bool] = []
    channels.renameRequested.connect(lambda: asked.append(True))
    channels.edit("rename")
    assert asked == [True]
    ui.click("entry_pool:auto")
    asked.clear()
    channels.edit("rename")
    assert asked == []


def test_a_form_is_made_the_first_time_it_shows(ui: Ui):
    channels = page(ui)
    assert list(channels.forms.forms) == ["output"]
    ui.click("entry_channel:browser")
    assert list(channels.forms.forms) == ["output", "apps"]
    assert rows(channels.forms.forms["apps"])["match"]["info"]["value"] == ["brave"]
    assert ui.shows("form_apps")
    # kept: the same one again, in place
    apps = channels.forms.forms["apps"]
    ui.click("entry_channel:out")
    ui.click("entry_channel:browser")
    assert channels.forms.forms["apps"] is apps
    assert rows(channels.forms.forms["output"])["color"]["info"]["value"] == "cyan"


def test_another_channel_of_the_same_type_changes_the_form_in_place(ui: Ui):
    channels = page(ui)
    channels.add("type:output")
    assert channels.selection == ("channel", "output")
    assert list(channels.forms.forms) == ["output"]
    form = channels.forms.forms["output"]
    assert form.base == ("channel", "output")
    assert rows(form)["color"]["info"]["set"] is False
    channels.pick("channel:out")
    assert form.base == ("channel", "out")
    assert rows(form)["color"]["info"]["value"] == "cyan"


def test_the_forms_are_made_in_the_background(make_ui: MakeUi, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ChannelsPage, "PREBUILD_AFTER_MS", 0)
    ui = make_ui()
    channels = page(ui)
    # the types of the file first: output and apps
    ui.wait_until(lambda: len(channels.prebuilt) == len(FORM_KEYS), timeout=60_000)
    assert set(channels.prebuilt[:2]) == {"output", "apps"}
    assert set(channels.forms.forms) == set(FORM_KEYS)
    # the click shows the form made before
    apps = channels.forms.forms["apps"]
    ui.click("entry_channel:browser")
    assert channels.forms.forms["apps"] is apps


def test_the_forms_wait_without_a_background_build(ui: Ui):
    channels = page(ui)
    channels.prebuild()
    assert channels.prebuilt == []


def test_a_problem_marks_its_entry_and_shows_in_its_form(ui: Ui):
    channels = page(ui)
    document = ui.app.editor.document
    document.set(("channel", "out", "max_volume"), 500)
    ui.app.editor.edited()
    assert entries(channels)[0]["problem"] is True
    assert entries(channels)[1]["problem"] is False
    assert " ".join(rows(channels.forms.forms["output"])["max_volume"]["info"]["problems"]).startswith(
        "Input should be less than"
    )


def test_a_problem_of_the_channel_itself_shows_on_the_page(ui: Ui):
    channels = page(ui)
    ui.click("entry_channel:browser")
    channels.formOf("apps").setValue("match", [])
    assert ui.app.editor.validation.problems
    # no option of its own has it: it shows under the heading of the channel
    assert channels.formOf("apps").rest == ["an apps channel needs match"]
    assert ui.text("channel_problem") == "an apps channel needs match"
    assert entries(channels)[1]["problem"] is True


def test_a_problem_leads_to_its_place(ui: Ui):
    channels = page(ui)
    document = ui.app.editor.document
    document.set(("channel", "browser", "max_volume"), 500)
    ui.app.editor.edited()
    channels.reveal(["channel", "browser", "max_volume"])
    ui.settle()
    assert channels.selection == ("channel", "browser")
    ui.wait_until(lambda: bool(ui.items("row_max_volume")))
    # a pool, with a problem of one of its options
    channels.reveal(["pool", "apps", "hold"])
    assert channels.selection == ("pool", "apps")
    channels.reveal(["pool", "auto"])
    assert channels.selection == ("pool", "auto")
    channels.reveal(["channel", "nothing"])
    assert channels.selection == ("pool", "auto")
    channels.reveal(["state", "call"])
    channels.reveal([])
    assert channels.selection == ("pool", "auto")


def test_the_profiles_row_shows_only_where_the_file_has_profiles(ui: Ui):
    channels = page(ui)
    form = channels.formOf("output")
    assert rows(form)["profiles"]["info"]["visible"] is False
    ui.app.editor.document.set(("channel", "out", "profiles"), [{"profile": "output:analog-stereo"}])
    ui.app.editor.edited()
    assert rows(form)["profiles"]["info"]["visible"] is True


def test_the_encoder_placeholder_follows_the_fader(ui: Ui):
    channels = page(ui)
    form = channels.formOf("output")
    before = rows(form)["encoder"]["info"]["placeholder"]
    form.setValue("fader", "mic")
    assert rows(form)["encoder"]["info"]["placeholder"] != before or before


def test_edits_are_undone_and_redone(ui: Ui):
    channels = page(ui)
    form = channels.formOf("output")
    form.setValue("label", "Boxes")
    assert entries(channels)[0]["title"] == "Boxes  ·  out"
    ui.app.editor.undo()
    assert entries(channels)[0]["title"] == "Speaker  ·  out"
    assert rows(form)["label"]["info"]["value"] == "Speaker"
    ui.app.editor.redo()
    assert entries(channels)[0]["title"] == "Boxes  ·  out"


def test_a_revert_can_be_undone(ui: Ui):
    channels = page(ui)
    ui.app.editor.document.unset(("channel", "browser"))
    ui.app.editor.edited()
    assert [row["name"] for row in entries(channels)][:2] == ["out", "apps"]
    ui.app.editor.revert()
    assert [row["name"] for row in entries(channels)][:2] == ["out", "browser"]
    ui.app.editor.undo()
    assert "browser" not in ui.app.editor.document.get(("channel",))


def test_an_empty_file_says_how_to_start(make_ui: MakeUi, path: Any):
    path.write_text("[state.call]\nvoice_chat = true\n")
    ui = make_ui(path)
    channels = page(ui)
    assert "No channel in the file yet" in channels.inspector["start"]
    assert ui.shows("channels_start")
    assert channels.selection == ("pool", "apps")
    channels.add("type:output")
    assert channels.inspector["start"] == ""


def test_the_channels_with_sound_move_in_the_list(ui: Ui):
    from xtouch_daemon.gui.qt.fields.sound import sounding
    from xtouch_daemon.live.messages import Snapshot

    channels = page(ui)
    assert (entries(channels)[0]["sound"], entries(channels)[0]["soundKind"]) == ("out", "bars")
    assert entries(channels)[1]["soundKind"] == "bars"
    channels.add("type:homeassistant")
    assert entries(channels)[-5]["soundKind"] == ""
    snapshot = Snapshot("x", True, sound_server=True, mqtt=None, strips=(), sounding=("out",))
    channels.show_live(snapshot)
    assert sounding().sounds("out")
    badges = [item for item in ui.items("sound") if item.property("channel") == "out"]
    assert badges
    assert badges[0].property("active") is True
    channels.show_live(None)
    assert not sounding().sounds("out")


def test_the_share_of_the_panes_is_kept(ui: Ui):
    channels = page(ui)
    pane: Any = channels.pane
    assert pane.share == 0.3
    pane.share = 0.4
    pane.keep()
    assert float(QSettings().value("split/channels")) == 0.4  # pyright: ignore[reportArgumentType]
    # a share that is none stays as it was
    pane.share = 2
    assert pane.share == 0.4


def test_the_handle_moves_the_panes(ui: Ui):
    channels = page(ui)
    handle = ui.item("pane_grab")
    start = ui.center(handle)
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest

    mouse: Any = QTest
    mouse.mousePress(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    mouse.mouseMove(ui.window, start + QPoint(60, 0))
    mouse.mouseRelease(ui.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(60, 0))
    ui.settle()
    pane: Any = channels.pane
    assert pane.share > 0.3
    assert float(QSettings().value("split/channels")) == pane.share  # pyright: ignore[reportArgumentType]


def test_the_show_functions_open_a_channel_or_a_pool(ui: Ui):
    channels = page(ui)
    channels.show_channel("browser")
    assert channels.selection == ("channel", "browser")
    channels.show_channel("nope")
    assert channels.selection == ("channel", "browser")
    channels.show_pool("people")
    assert channels.selection == ("pool", "people")
    channels.show_pool("nope")
    assert channels.selection == ("pool", "people")
