"""
The virtual twin in the daemon: a second set of strips for a client of the live view, that touches nothing real.
"""

import asyncio
from pathlib import Path

import pytest

from tests.support.audio import FakeBackend
from tests.support.daemon import STATE
from tests.support.hardware import RecordingSurface
from tests.support.waiting import until
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.live.messages import EndPreview, KeepPreview, Play, Reply, StartPreview, TwinView
from xtouch_daemon.runtime import daemon as daemon_module
from xtouch_daemon.runtime.daemon import Daemon
from xtouch_daemon.slots.outcomes import Situation

GAME = """
[channel.speaker]
type = "output"
label = "Speaker"
color = "cyan"

[channel.game]
type = "apps"
match = ["mygame"]
label = "Game"
color = "red"

[state.gaming]
mode = true

[slots]
1 = "speaker"
2 = ["game if gaming", "auto"]
"""
HOME = Situation("default", frozenset(), frozenset())
GAMING = Situation("gaming", frozenset(), frozenset(), people=1, apps=1)


class Views(list[tuple[object, TwinView]]):
    """What the daemon sent to the clients' twins."""

    def of(self, client: object) -> list[TwinView]:
        return [view for to, view in self if to is client]


@pytest.fixture
def made(config_path: Path, surface: RecordingSurface, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch):
    daemon = Daemon(
        parse_config(config_path.read_text()),
        backend,
        surface,
        config_path,
        live_socket=config_path.with_name("live.sock"),
    )
    views = Views()
    assert daemon.live is not None
    monkeypatch.setattr(daemon.live, "tell_view", lambda client, view: views.append((client, view)))
    told: list[tuple[object, Reply]] = []
    monkeypatch.setattr(daemon.live, "tell", lambda client, reply: told.append((client, reply)))
    daemon.mixer.on_state(STATE)
    daemon.told = told  # pyright: ignore[reportAttributeAccessIssue]
    return daemon, views


async def test_a_twin_shows_its_configuration_in_its_situation_and_touches_nothing_real(
    made: tuple[Daemon, Views], surface: RecordingSurface, backend: FakeBackend
):
    daemon, views = made
    gui = object()
    real = list(surface.sent)
    texts = [list(strip.text) for strip in surface.strips]
    calls = list(backend.calls)

    assert daemon.on_request(gui, StartPreview(GAME, GAMING, on_device=False)) == Reply("preview", True)
    # sent as it changes, without asking
    await until(lambda: views.of(gui) and views.of(gui)[-1].strips[1].text[0] == "Game")
    view = views.of(gui)[-1]
    assert view.slots.mode == "gaming"
    assert view.strips[0].text[0] == "Speaker"
    # the real strips, the sound server and the real state are as they were
    assert [list(strip.text) for strip in surface.strips] == texts
    assert surface.sent == real
    assert backend.calls == calls
    assert daemon.mixer.state is STATE


async def test_a_twin_follows_a_new_request_and_plays(made: tuple[Daemon, Views]):
    daemon, views = made
    gui = object()
    daemon.on_request(gui, StartPreview(GAME, HOME, on_device=False))
    daemon.on_request(gui, StartPreview(GAME, GAMING, on_device=False))
    assert len(daemon._twins) == 1
    await until(lambda: views.of(gui) and views.of(gui)[-1].slots.mode == "gaming")
    twin = daemon._twins[gui].twin
    daemon.on_request(gui, Play(protocol.ButtonPressed(0, protocol.Button.MUTE, True), preview=True))
    assert twin.surface.mirror is not None


async def test_a_configuration_with_errors_is_refused_and_the_twin_runs_on(made: tuple[Daemon, Views]):
    daemon, _ = made
    gui = object()
    daemon.on_request(gui, StartPreview(GAME, HOME, on_device=False))
    reply = daemon.on_request(gui, StartPreview('[slots]\n1 = "nothing"\n', HOME, on_device=False))
    assert reply is not None
    assert not reply.ok
    assert reply.kind == "preview"
    assert gui in daemon._twins
    nomode = daemon.on_request(gui, StartPreview(GAME, Situation("nomode", frozenset(), frozenset()), on_device=False))
    assert nomode is not None
    assert not nomode.ok


async def test_a_twin_ends_on_request_with_its_client_and_without_a_heartbeat(
    made: tuple[Daemon, Views], monkeypatch: pytest.MonkeyPatch
):
    daemon, _ = made
    told: list[tuple[object, Reply]] = daemon.told  # pyright: ignore[reportAttributeAccessIssue]
    a, b, c = object(), object(), object()
    for client in (a, b, c):
        daemon.on_request(client, StartPreview(GAME, HOME, on_device=False))
    assert len(daemon._twins) == 3

    daemon.on_request(a, EndPreview())
    assert a not in daemon._twins
    daemon.on_request(b, KeepPreview())
    daemon.on_client_closed(c)
    assert c not in daemon._twins

    monkeypatch.setattr(daemon_module, "PREVIEW_TIMEOUT", 0.0)
    monkeypatch.setattr(daemon_module, "PREVIEW_CHECK", 0.01)
    follower = asyncio.create_task(daemon._watch_twins())
    try:
        await until(lambda: not daemon._twins)
    finally:
        follower.cancel()
    assert [reply.kind for to, reply in told if to is b] == ["ended"]


async def test_a_play_without_a_twin_does_nothing(made: tuple[Daemon, Views]):
    daemon, _ = made
    daemon.on_request(object(), Play(protocol.FaderTouched(0, True), preview=True))
    assert not daemon._twins
