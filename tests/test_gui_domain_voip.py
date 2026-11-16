from pathlib import Path

from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.voip import install_hint, install_steps, participants, people_on_strips
from xtouch_daemon.live import Snapshot, VoipState
from xtouch_daemon.mumble import Setup


def snapshot(voip: VoipState | None) -> Snapshot:
    return Snapshot("abc", True, True, None, (), voip=voip)


VOIP = VoipState("bridge", True, "mumble", "Lobby", 2, ("Ann", "Bob"), (None, "Bob", "Ann"))


def test_the_people_in_the_voice_chat_are_suggested():
    assert participants(snapshot(VOIP)) == (
        Suggestion("Ann", "in the voice chat now"),
        Suggestion("Bob", "in the voice chat now"),
    )
    assert participants(snapshot(None)) == ()
    assert participants(None) == ()


def test_who_is_on_which_strip():
    assert people_on_strips(snapshot(VOIP), 4) == (None, "Bob", "Ann", None)
    assert people_on_strips(snapshot(None), 2) == (None, None)
    assert people_on_strips(None, 1) == (None,)


def test_what_install_does():
    assert install_hint(Setup(None, False, None, False)).startswith("Mumble is not installed")
    assert install_hint(Setup(None, False, None, True)).startswith("There is no plugin to install")
    assert install_hint(Setup(None, True, None, True)).startswith("Builds the plugin")
    assert install_hint(Setup(Path("/b"), False, None, True)).startswith("Opens it")


def test_the_steps_say_whether_mumble_has_the_plugin():
    assert install_steps(Setup(None, True, None, True))[0].endswith("Mumble asks: confirm.")
    assert "(/p/libxtouch-daemon.so)" in install_steps(Setup(None, True, Path("/p/libxtouch-daemon.so"), True))[0]
