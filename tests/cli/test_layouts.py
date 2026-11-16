"""
`layout`.
"""

import contextlib
import socket
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.support.cli import invoke
from xtouch_daemon import cli
from xtouch_daemon.cli import layouts as layout_commands
from xtouch_daemon.cli.configuration import describe_strip
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.config.layout_strips import InheritStripConfig
from xtouch_daemon.live.codec import decode_request, encode, encode_reply
from xtouch_daemon.live.messages import FEATURES, Reply, Request, Snapshot, SwitchLayout


def test_check_config_shows_the_layouts(tmp_path: Path) -> None:
    path = tmp_path / "layouts.toml"
    path.write_text(
        '[[strip]]\ntype = "output"\n[voip]\n'
        '[[layout]]\nname = "gaming"\nlabel = "Gaming"\napps = ["steam"]\nprocesses = ["mumble", "ts3"]\npriority = 2\n'
        '[[layout.strip]]\ntype = "inherit"\n[[layout.strip]]\ntype = "voip"\n'
        '[[layout.strip]]\ntype = "voip"\nperson = ["Ann", "ann-phone"]\nlabel = "Mum"\ncollapse = true\n'
        '[[layout.strip]]\ntype = "voip"\nperson = "Bob"\n'
        '[[layout]]\nname = "plain"\n[[layout]]\nname = "music"\napps = ["spotify"]\n'
    )
    lines = invoke("check-config", "-c", str(path)).output.splitlines()
    gaming = lines.index("Layout gaming (Gaming), while steam has a stream or mumble or ts3 runs, priority 2:")
    assert lines[gaming + 1].startswith("  1. the default output")
    assert lines[gaming + 1].endswith("), from the default layout, strip 1")
    assert lines[gaming + 2] == "  2. a participant of the voice chat, in the group (white, talking: green)"
    assert (
        lines[gaming + 3]
        == "  3. 'Mum' Ann or ann-phone in the voice chat, dark while away (white, talking: green, collapses)"
    )
    assert lines[gaming + 4] == "  4. Bob in the voice chat, dark while away (white, talking: green)"
    assert "Layout plain:" in lines
    assert "Layout music, while spotify has a stream:" in lines
    config = parse_config('[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "inherit"\n')
    assert describe_strip(config.layouts[0].strips[0], 1) == "the strip of the default layout at this place"
    other = InheritStripConfig(type="inherit", layout="voice", strip="music")
    assert describe_strip(other, 1) == "strip music of layout voice"


def test_check_config_tells_where_inherited_strips_come_from(tmp_path: Path) -> None:
    path = tmp_path / "inherit.toml"
    path.write_text(
        '[[strip]]\ntype = "output"\n[[layout]]\nname = "a"\n[[layout.strip]]\ntype = "empty"\n'
        '[[layout.strip]]\ntype = "inherit"\n[[layout]]\nname = "b"\n[[layout.strip]]\ntype = "inherit"\n'
        'layout = "a"\nstrip = 1\n'
    )
    lines = invoke("check-config", "-c", str(path)).output.splitlines()
    a = lines.index("Layout a:")
    assert lines[a + 2].endswith("encoder: pick), from the default layout, an auto strip")
    assert lines[lines.index("Layout b:") + 1] == "  1. empty, from layout a, strip 1"


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
    config = parse_config(
        '[voip]\n[[strip]]\ntype = "apps"\nmatch = ["mumble"]\nlabel = "VoIP"\n'
        'launch = ["mumble", "mumble://me@example.org/Gaming Night"]\n'
        '[[strip]]\ntype = "auto"\nlaunch = "spotify"\nlaunch_when_running = true\n'
        '[[strip]]\ntype = "voip"\nlaunch = ["mumble"]\n'
    )
    apps, auto, voip = config.strips[:3]
    assert describe_strip(apps, 1) == (
        "'VoIP' applications mumble, select launches mumble 'mumble://me@example.org/Gaming Night' while it does "
        "not run (white, rec: recording, solo: off, encoder: media)"
    )
    assert "the next application that plays, select launches spotify also while it runs (" in describe_strip(auto, 2)
    assert describe_strip(voip, 3).endswith(", select launches mumble while it is not there")


def test_check_config_names_meters_after_the_fader(tmp_path: Path) -> None:
    path = tmp_path / "meters.toml"
    path.write_text(
        '[[strip]]\ntype = "output"\nmeter_point = "post_fader"\n'
        '[[strip]]\ntype = "input"\nmeter_point = "post_fader"\nmeter = false\n'
        '[[layout]]\nname = "quiet"\nmeter_point = "post_fader"\n[[layout.strip]]\ntype = "inherit"\nstrip = 2\n'
    )
    lines = invoke("check-config", "-c", str(path)).output.splitlines()
    # before the fader is the default: not worth a word; without a meter neither
    assert lines[1] == "  1. the default output (white, meter post-fader, rec: recording, solo: off, encoder: balance)"
    assert lines[2] == "  2. the default input (white, no meter, rec: recording, solo: off, encoder: balance)"
    assert lines[3] == "  3. the next application that plays (white, rec: recording, solo: off, encoder: pick)"
    quiet = lines.index("Layout quiet:")
    assert "(white, meter post-fader, rec" in lines[quiet + 2]
