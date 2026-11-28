"""
The popovers of the bar over the drawing in Qt Quick (`DevicePanel.popover`): what the pills say, the modes and
states the daemon reports, and the buttons in them.
"""

from pytestqt.qtbot import QtBot

from tests.gui.quick.conftest import MakeUi
from tests.gui.quick.device_support import device_of, live_ui
from tests.support.gui import FakeLiveDaemon
from xtouch_daemon.live.messages import SetMode, SlotsState, SlotView, StateView


def state(name: str, value: bool, mode: bool, source: str | None = None, override: str = "auto") -> StateView:
    return StateView(name, value, mode, None, source, override)


def slots(mode: str = "default", pick: str | None = None) -> SlotsState:
    states = (
        state("gaming", mode == "gaming", True, "game runs" if mode == "gaming" else None),
        state("call", True, False, "mumble runs", "off"),
        state("music", False, False),
    )
    return SlotsState(mode, pick, (SlotView(1, 0, "game", None, None, ()),), states, {})


def test_an_unknown_popover_is_empty(make_ui: MakeUi) -> None:
    ui = make_ui()
    device = device_of(ui)
    assert device.popover("nothing") == {}
    # no slots told yet, no virtual device hosted
    assert device.popover("modes") == {}
    assert device.popover("virtual") == {}


def test_the_live_popover_explains_the_drawing(qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot)
    shown = device_of(ui).popover("live")
    assert shown["heading"] == "Drawing"
    (entry,) = shown["entries"]
    assert entry["tone"] == device_of(ui).liveStatus["tone"]
    assert entry["text"] == device_of(ui).liveStatus["tip"]


def test_the_live_popover_offers_the_virtual_device(qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, device=False, virtual=True)
    device = device_of(ui)
    shown = device.popover("live")
    (entry,) = shown["entries"]
    assert entry["actions"] == ["Open the virtual device"]
    device.activate(0, 0)
    assert device.hosted is not None


def test_the_modes_popover_lists_the_modes_and_the_states(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, slots=slots())
    device = device_of(ui)
    ui.wait_until(lambda: device.modeStatus != {})

    shown = device.popover("modes")

    assert shown["heading"] == "Mode and states"
    assert shown["intro"]
    mode, group, call, music = shown["entries"]
    assert mode["title"] == "Mode"
    assert mode["text"] == "The rules pick it."
    assert mode["actions"] == ["Pick gaming"]
    assert group["title"] == "States"
    assert (call["title"], call["statusText"]) == ("call", "on")
    assert call["text"] == "Mumble runs. Overridden: off."
    assert (music["statusText"], music["text"]) == ("off", "None of its sources is on.")

    device.activate(0, 0)
    ui.wait_until(lambda: SetMode("gaming") in live_daemon.requests)


def test_a_mode_picked_by_hand_goes_back_to_the_rules(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, slots=slots("gaming", "gaming"))
    device = device_of(ui)
    ui.wait_until(lambda: device.modeStatus != {})

    (mode, *_rest) = device.popover("modes")["entries"]

    assert mode["text"] == "Picked by hand, until the rules want another one."
    assert mode["actions"] == ["Pick no mode", "Back to the rules"]
    device.activate(0, 1)
    ui.wait_until(lambda: SetMode("auto") in live_daemon.requests)


def test_the_pill_of_the_mode_opens_its_popover_in_the_window(
    qtbot: QtBot, make_ui: MakeUi, live_daemon: FakeLiveDaemon
) -> None:
    ui = live_ui(make_ui, live_daemon, qtbot, slots=slots())
    device = device_of(ui)
    ui.wait_until(lambda: device.modeStatus != {})
    ui.grab()

    ui.click("modePill")
    ui.settle()

    assert ui.find("popoverEntry_Mode") is not None
    ui.click("popoverAction_Pick gaming")
    ui.wait_until(lambda: SetMode("gaming") in live_daemon.requests)
