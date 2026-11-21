import dataclasses
from pathlib import Path

from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.voip import install_hint, install_steps, participants, voip_status
from xtouch_daemon.live.messages import Snapshot, VoipClient, VoipState
from xtouch_daemon.voip.mumble import Setup


def snapshot(voip: VoipState | None) -> Snapshot:
    return Snapshot("abc", True, True, None, (), voip=voip)


VOIP = VoipState("bridge", True, "mumble", "Lobby", 2, ("Ann", "Bob"))


def test_the_people_in_the_voice_chat_are_suggested():
    assert participants(snapshot(VOIP)) == (
        Suggestion("Ann", "in the voice chat now"),
        Suggestion("Bob", "in the voice chat now"),
    )
    assert participants(snapshot(None)) == ()
    assert participants(None) == ()


def test_what_install_does():
    assert install_hint(Setup(None, False, None, False)).startswith("Mumble is not installed")
    assert install_hint(Setup(None, False, None, True)).startswith("There is no plugin to install")
    assert install_hint(Setup(None, True, None, True)).startswith("Builds the plugin")
    assert install_hint(Setup(Path("/b"), False, None, True)).startswith("Copies it")


def test_the_steps_say_whether_mumble_has_the_plugin():
    assert install_steps(Setup(None, True, None, True))[0].endswith("Mumble asks: confirm.")
    assert "(/p/libxtouch-daemon.so)" in install_steps(Setup(None, True, Path("/p/libxtouch-daemon.so"), True))[0]


def test_the_status_lists_each_client_with_its_channel():
    both = VoipState(
        "bridge",
        True,
        "mumble, teamspeak",
        "Lobby",
        3,
        clients=(VoipClient("mumble", "Lobby"), VoipClient("teamspeak")),
    )
    status = voip_status(snapshot(both))
    assert (status.text, status.tip) == ("Mumble and TeamSpeak connected", "3 people: Mumble in Lobby, TeamSpeak.")
    one = dataclasses.replace(both, client="mumble", participants=1, clients=(VoipClient("mumble", "Lobby"),))
    assert voip_status(snapshot(one)).tip == "1 person in Lobby."
