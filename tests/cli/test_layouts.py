"""
`mode`, `layout`, and what `check-config` says about strips.
"""

import contextlib
import dataclasses
import socket
import threading
from pathlib import Path

from click.testing import CliRunner

from tests.support.cli import invoke
from tests.support.strips import strips_of
from xtouch_daemon import cli
from xtouch_daemon.cli.configuration import describe_strip
from xtouch_daemon.live.codec import decode_request, encode, encode_reply
from xtouch_daemon.live.messages import Reply, Request, SetMode, SlotsState, Snapshot, StateView


def test_layout_points_to_mode() -> None:
    for args in ((), ("gaming",), ("--next",)):
        result = CliRunner().invoke(cli.main, ["layout", *args])
        assert result.exit_code == 1
        assert "layouts are gone: `xtouch-daemon mode` lists and picks the modes" in result.output


def test_check_config_shows_what_select_launches() -> None:
    (apps, auto) = strips_of(
        '[[strip]]\ntype = "apps"\nmatch = ["mumble"]\nlabel = "VoIP"\n'
        'launch = ["mumble", "mumble://me@example.org/Gaming Night"]\n'
        '[[strip]]\ntype = "auto"\nlaunch = "spotify"\nlaunch_when_running = true\n'
    )
    assert describe_strip(apps, "voip") == (
        "'VoIP' applications mumble, select launches mumble 'mumble://me@example.org/Gaming Night' while it does "
        "not run (white, rec: recording, solo: off, encoder: media)"
    )
    assert "the next application that plays, select launches spotify also while it runs (" in describe_strip(auto, "a")
    (output, empty, other) = strips_of(
        '[[strip]]\ntype = "output"\nmeter_point = "post_fader"\n[[strip]]\ntype = "empty"\n'
        '[[strip]]\ntype = "voip"\nperson = "Ann"\nlabel = "Mum"\n'
    )
    assert describe_strip(output, "out", "post_fader") == (
        "the default output (white, meter post-fader, rec: recording, solo: off, encoder: balance)"
    )
    assert describe_strip(empty, "x") == "empty"
    assert describe_strip(other, "ann") == "'Mum' Ann in the voice chat, dark while away (white, talking: green)"


SLOTS = SlotsState(
    "default",
    None,
    (),
    (StateView("gaming", False, True, None, None, "auto"), StateView("call", False, False, None, None, "auto")),
    {},
)


class FakeModes:
    """A daemon with channels, states and slots on a socket in a thread: tells its modes, picks one on a request."""

    def __init__(self, path: Path, slots: SlotsState | None = SLOTS, answers: bool = True):
        self.slots = slots
        self.answers = answers
        self.requests: list[Request] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        connection, _ = self.server.accept()
        with connection, connection.makefile("rb") as lines:
            # an older line first, which the client skips
            snapshot = Snapshot("abc", True, True, None, (), slots=self.slots, layouts=("default",))
            connection.sendall(b'{"version": 0}\n' + encode(snapshot))
            for line in lines:
                request = decode_request(line)
                self.requests.append(request)
                assert isinstance(request, SetMode)
                if not self.answers:
                    return
                if request.mode == "nope":
                    reply = Reply("mode", False, "There is no mode nope (auto, default, gaming)")
                else:
                    reply = Reply("mode", True, "gaming" if request.mode in ("gaming", "+1") else "default")
                with contextlib.suppress(OSError):
                    connection.sendall(encode_reply(reply))

    def close(self) -> None:
        self.server.close()
        self.thread.join(2)


def test_mode_lists_and_picks_the_modes(live_socket: Path) -> None:
    fake = FakeModes(live_socket)
    assert invoke("mode").output.splitlines() == ["* default", "  gaming", "picked by the rules"]
    fake.close()
    for args, shown, sent in (
        (("gaming",), "Mode gaming", "gaming"),
        (("--next",), "Mode gaming", "+1"),
        (("--previous",), "Mode default", "-1"),
        (("auto",), "Mode default", "auto"),
    ):
        live_socket.unlink()
        fake = FakeModes(live_socket)
        assert invoke("mode", *args).output.strip() == shown
        assert fake.requests == [SetMode(sent)]
        fake.close()


def test_mode_by_hand_and_errors(live_socket: Path) -> None:
    fake = FakeModes(live_socket, dataclasses.replace(SLOTS, mode_pick="default"))
    assert invoke("mode").output.splitlines()[-1] == "picked by hand"
    fake.close()
    live_socket.unlink()
    fake = FakeModes(live_socket)
    result = CliRunner().invoke(cli.main, ["mode", "nope"])
    assert "There is no mode nope" in result.output
    fake.close()
    live_socket.unlink()
    fake = FakeModes(live_socket, answers=False)
    assert "did not pick the mode" in CliRunner().invoke(cli.main, ["mode", "gaming"]).output
    fake.close()
    live_socket.unlink()
    fake = FakeModes(live_socket, None)
    assert "older than this program, restart it" in CliRunner().invoke(cli.main, ["mode"]).output
    fake.close()


def test_mode_without_a_daemon(live_socket: Path) -> None:
    assert "the daemon does not run" in CliRunner().invoke(cli.main, ["mode"]).output


def test_mode_of_a_daemon_that_says_nothing(live_socket: Path) -> None:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(live_socket))
    server.listen(1)

    def serve() -> None:
        connection, _ = server.accept()
        connection.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert "did not answer" in CliRunner().invoke(cli.main, ["mode"]).output
    thread.join(2)
    server.close()
