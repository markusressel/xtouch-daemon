"""
What the shell gives the pages from the live view of the daemon: each snapshot, the places of the preview, the
situation of Simulate, and what the forms reach (one owner of the live plumbing: the drawing only reads it).
"""

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.device_support import device_of, live_ui
from tests.gui.quick.slots_helpers import page
from tests.gui.quick.test_device_popovers import slots
from tests.support.gui import FakeLiveDaemon
from xtouch_daemon.gui.domain.live_preview import Place
from xtouch_daemon.gui.quick.forms.context import forms_of
from xtouch_daemon.gui.quick.pages.settings import SettingsPage
from xtouch_daemon.live.messages import SetMode


def test_the_drawing_and_the_window_share_one_live_view(make_ui: MakeUi) -> None:
    ui = make_ui()
    shell = ui.app.shell
    device = device_of(ui)

    assert not hasattr(device, "live")
    assert device.shell is shell
    assert device.device_test.live is shell.live
    assert [shell.live_preview.place, shell.hosted, shell.trying] == [Place.GUI, None, None]


def test_every_snapshot_reaches_the_pages_and_the_forms(
    make_ui: MakeUi, live_daemon: FakeLiveDaemon, qtbot: object
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, slots=slots())
    shell = ui.app.shell

    # the page Slots reaches the snapshot, the twin and the daemon through the shell's live view
    told = shell.live.snapshot
    assert told is not None
    assert page(ui).live.snapshot() is told
    assert page(ui).live.request == shell.live.send
    assert page(ui).live.shows_twin() == shell.live_preview.in_gui
    assert page(ui).live.audio() is shell.audio
    # ... and showed it: it knows what the daemon shows
    assert page(ui).shown_live is not None
    # the page Settings shows the connection of the daemon
    settings = ui.app.settings
    assert isinstance(settings, SettingsPage)
    assert settings.snapshot is told
    # the forms read the same snapshot, and send through the same connection
    context = forms_of(ui.app)
    assert context.snapshot() is told
    assert context.known() == shell.live.known
    context.send(SetMode("gaming"))
    ui.wait_until(lambda: SetMode("gaming") in live_daemon.requests)


def test_the_note_of_simulate_follows_the_place_of_the_preview(make_ui: MakeUi) -> None:
    ui = make_ui(find_daemon=lambda: None)
    shell = ui.app.shell

    assert page(ui).deviceNote == shell.placeText
    assert shell.placeText.startswith("Nowhere: ")
    shell.setPlace("off")
    assert page(ui).deviceNote == shell.placeText


def test_the_situation_of_simulate_reaches_the_preview(
    make_ui: MakeUi, live_daemon: FakeLiveDaemon, qtbot: object
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, slots=slots())
    shell = ui.app.shell
    assert shell.live_preview.situation is None

    page(ui).toggleSimulate(True)

    assert shell.live_preview.situation == page(ui).what_if
    assert shell.live_preview.situation is not None
    page(ui).toggleSimulate(False)
    assert shell.live_preview.situation is None
