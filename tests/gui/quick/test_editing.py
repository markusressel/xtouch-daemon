"""The Edit protocol of the pages Channels and States: `reveal` picks the entry and shows the option."""

from tests.support.quick import Ui
from xtouch_daemon.gui.quick.pages.channels import ChannelsPage
from xtouch_daemon.gui.quick.pages.states import StatesPage


def test_reveal_picks_the_state_of_the_path(ui: Ui):
    ui.app.showPage("states")
    ui.settle()
    states = ui.app.states
    assert isinstance(states, StatesPage)
    states.add("kind:state")
    assert states.selection != "call"
    states.reveal(["state", "call", "delay_on"])
    ui.settle()
    assert states.selection == "call"


def test_reveal_picks_the_channel_of_the_path(ui: Ui):
    ui.app.showPage("channels")
    ui.settle()
    channels = ui.app.channels
    assert isinstance(channels, ChannelsPage)
    channels.reveal(["channel", "browser", "match"])
    ui.settle()
    assert channels.selection == ("channel", "browser")
