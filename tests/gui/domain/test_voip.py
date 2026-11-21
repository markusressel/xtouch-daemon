from pathlib import Path

import pytest

from xtouch_daemon.gui.domain import voip
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.voip import (
    MUMBLE,
    TEAMSPEAK,
    PluginSetup,
    connected_here,
    display_name,
    install_hint,
    install_steps,
    participants,
)
from xtouch_daemon.live.messages import Snapshot, VoipState
from xtouch_daemon.voip import mumble, teamspeak


def snapshot(state: VoipState | None) -> Snapshot:
    return Snapshot("abc", True, True, None, (), voip=state)


VOIP = VoipState("bridge", True, "mumble", "Lobby", 2, ("Ann", "Bob"))


def test_the_people_in_the_voice_chat_are_suggested():
    assert participants(snapshot(VOIP)) == (
        Suggestion("Ann", "in the voice chat now"),
        Suggestion("Bob", "in the voice chat now"),
    )
    assert participants(snapshot(None)) == ()
    assert participants(None) == ()


def test_what_install_does():
    assert install_hint(MUMBLE, PluginSetup(None, False, None, False)).startswith("Mumble is not installed")
    assert "the package teamspeak3" in install_hint(TEAMSPEAK, PluginSetup(None, False, None, False))
    assert install_hint(MUMBLE, PluginSetup(None, False, None, True)).startswith("There is no plugin to install")
    assert install_hint(MUMBLE, PluginSetup(None, True, None, True)).startswith("Builds the plugin")
    assert install_hint(TEAMSPEAK, PluginSetup(Path("/b"), False, None, True)) == (
        'Copies it into ~/.ts3client/plugins; then TeamSpeak needs "Reload All" in Tools, Options, Addons.'
    )


def test_the_steps_say_whether_the_client_has_the_plugin():
    assert install_steps(MUMBLE, PluginSetup(None, True, None, True))[0].endswith(
        "It goes into Mumble's plugin directory."
    )
    steps = install_steps(TEAMSPEAK, PluginSetup(None, True, Path("/p/x.so"), True))
    assert steps[0] == '"Install TeamSpeak plugin" below. TeamSpeak has the plugin (/p/x.so).'
    assert steps[1].startswith("In TeamSpeak: Tools, Options, Addons")


def test_whose_plugin_is_connected():
    assert connected_here(snapshot(VOIP), MUMBLE)
    assert not connected_here(snapshot(VOIP), TEAMSPEAK)
    both = VoipState("bridge", True, "Mumble, teamspeak", None, 0)
    assert connected_here(snapshot(both), MUMBLE)
    assert connected_here(snapshot(both), TEAMSPEAK)
    assert not connected_here(snapshot(VoipState("bridge", False, "mumble", None, 0)), MUMBLE)
    assert not connected_here(snapshot(None), MUMBLE)
    assert not connected_here(None, MUMBLE)
    assert display_name("teamspeak") == "TeamSpeak"
    assert display_name("discord") == "Discord"


def test_the_setups_of_the_clients(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mumble, "setup", lambda: mumble.Setup(Path("/b"), True, Path("/i"), True))
    monkeypatch.setattr(teamspeak, "setup", lambda: teamspeak.Setup(None, False, None, True))
    assert voip.mumble_setup() == PluginSetup(Path("/b"), True, Path("/i"), True)
    assert voip.teamspeak_setup() == PluginSetup(None, False, None, True)
    assert not voip.teamspeak_setup().installable
