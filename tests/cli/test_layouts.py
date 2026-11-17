"""
`layout`.
"""

import contextlib
import dataclasses
import socket
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.cli import invoke
from tests.support.strips import strips_of
from xtouch_daemon import cli
from xtouch_daemon.cli import layouts as layout_commands
from xtouch_daemon.cli.configuration import describe_strip
from xtouch_daemon.live.codec import decode_request, encode, encode_reply
from xtouch_daemon.live.messages import FEATURES, Reply, Request, SetMode, SlotsState, Snapshot, StateView, SwitchLayout


class FakeLive:
    """
    A daemon's live view on a socket in a thread: tells its layouts, and switches on a request (if `obeys`, otherwise
    it hangs up). `refuses` answers it with the reason why not, like the daemon does for a layout it does not have.
    """

    def __init__(
        self,
        path: Path,
        layouts: tuple[str, ...],
        obeys: bool = True,
        answers: bool = True,
        refuses: str | None = None,
        features: tuple[str, ...] = FEATURES,
    ):
        self.path = path
        self.layout = layouts[0] if layouts else None
        self.layouts = layouts
        self.obeys = obeys
        self.answers = answers
        self.refuses = refuses
        self.features = features
        self.requests: list[Request] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _line(self) -> bytes:
        snapshot = Snapshot(
            "abc", True, True, None, (), features=self.features, layout=self.layout, layouts=self.layouts
        )
        return encode(snapshot)

    def _serve(self) -> None:
        connection, _ = self.server.accept()
        with connection, connection.makefile("rb") as lines:
            if not self.answers:
                lines.readline()
                return
            # an older line first, which the client skips
            connection.sendall(b'{"version": 0}\n' + self._line())
            for line in lines:
                request = decode_request(line)
                self.requests.append(request)
                assert isinstance(request, SwitchLayout)
                if not self.obeys:
                    return
                if self.refuses is not None:
                    reply = Reply("layout", False, self.refuses)
                else:
                    self.layout = request.layout
                    reply = Reply("layout", True, request.layout)
                with contextlib.suppress(OSError):
                    # a snapshot may come before the reply
                    connection.sendall(self._line() + encode_reply(reply))

    def close(self) -> None:
        self.server.close()
        self.thread.join(2)


def test_layout_lists_the_layouts(live_socket: Path) -> None:
    fake = FakeLive(live_socket, ("default", "gaming"))
    assert invoke("layout").output.splitlines() == ["* default", "  gaming"]
    fake.close()


def test_layout_of_a_daemon_without_layouts(live_socket: Path) -> None:
    fake = FakeLive(live_socket, ())
    assert invoke("layout").output.splitlines() == ["  default"]
    fake.close()


@pytest.mark.parametrize(
    ("args", "wanted"),
    [(("gaming",), "gaming"), (("--next",), "gaming"), (("--previous",), "voice"), (("default",), "default")],
)
def test_layout_switches_the_daemon(live_socket: Path, args: tuple[str, ...], wanted: str) -> None:
    fake = FakeLive(live_socket, ("default", "gaming", "voice"))
    assert invoke("layout", *args).output == f"Layout {wanted}\n"
    fake.close()
    assert fake.requests == [SwitchLayout(wanted)]


def test_layout_reports_what_goes_wrong(live_socket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = CliRunner().invoke(cli.main, ["layout"])
    assert result.exit_code == 1
    assert "the daemon does not run" in result.output

    fake = FakeLive(live_socket, ("default", "gaming"))
    result = CliRunner().invoke(cli.main, ["layout", "nope"])
    assert "there is no layout nope (default, gaming)" in result.output
    fake.close()
    live_socket.unlink()

    fake = FakeLive(live_socket, ("default", "gaming"), obeys=False)
    result = CliRunner().invoke(cli.main, ["layout", "gaming"])
    assert "the daemon did not switch to gaming" in result.output
    fake.close()
    live_socket.unlink()

    fake = FakeLive(live_socket, ("default", "gaming"), refuses="There is no layout gaming (default)")
    result = CliRunner().invoke(cli.main, ["layout", "gaming"])
    assert "Error: There is no layout gaming (default)" in result.output
    fake.close()
    live_socket.unlink()

    # one from before the requests of the live view
    fake = FakeLive(live_socket, ("default", "gaming"), features=())
    result = CliRunner().invoke(cli.main, ["layout", "gaming"])
    assert "the daemon is older than this program, restart it" in result.output
    fake.close()
    live_socket.unlink()

    monkeypatch.setattr(layout_commands, "LAYOUT_TIMEOUT", 0.05)
    fake = FakeLive(live_socket, ("default",), answers=False)
    result = CliRunner().invoke(cli.main, ["layout"])
    assert "the daemon did not answer" in result.output
    fake.close()


def test_check_config_shows_what_select_launches() -> None:
    (apps, auto, voip) = strips_of(
        '[[strip]]\ntype = "apps"\nmatch = ["mumble"]\nlabel = "VoIP"\n'
        'launch = ["mumble", "mumble://me@example.org/Gaming Night"]\n'
        '[[strip]]\ntype = "auto"\nlaunch = "spotify"\nlaunch_when_running = true\n'
        '[[strip]]\ntype = "voip"\nlaunch = ["mumble"]\n'
    )
    assert describe_strip(apps, "voip") == (
        "'VoIP' applications mumble, select launches mumble 'mumble://me@example.org/Gaming Night' while it does "
        "not run (white, rec: recording, solo: off, encoder: media)"
    )
    assert "the next application that plays, select launches spotify also while it runs (" in describe_strip(auto, "a")
    assert describe_strip(voip, "b").endswith(", select launches mumble while it is not there")
    (output, empty, other) = strips_of(
        '[[strip]]\ntype = "output"\nmeter_point = "post_fader"\ncollapse = true\n[[strip]]\ntype = "empty"\n'
        '[[strip]]\ntype = "voip"\nperson = "Ann"\nlabel = "Mum"\ncollapse = true\n'
    )
    assert describe_strip(output, "out", "post_fader") == (
        "the default output (white, meter post-fader, rec: recording, solo: off, encoder: balance, collapses)"
    )
    assert describe_strip(empty, "x") == "empty"
    assert (
        describe_strip(other, "ann")
        == "'Mum' Ann in the voice chat, dark while away (white, talking: green, collapses)"
    )


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
            connection.sendall(encode(Snapshot("abc", True, True, None, (), slots=self.slots, layouts=("default",))))
            for line in lines:
                request = decode_request(line)
                self.requests.append(request)
                assert isinstance(request, SetMode | SwitchLayout)
                if not self.answers:
                    return
                if isinstance(request, SwitchLayout):
                    reply = Reply("layout", True, request.layout)
                elif request.mode == "nope":
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
    assert "see `xtouch-daemon layout`" in CliRunner().invoke(cli.main, ["mode"]).output
    fake.close()
    # layout on a daemon with modes still works, and says what replaces it
    live_socket.unlink()
    fake = FakeModes(live_socket)
    result = CliRunner().invoke(cli.main, ["layout", "default"])
    assert "`xtouch-daemon mode` replaces `layout`" in result.output
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
