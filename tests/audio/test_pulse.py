import asyncio
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import pulsectl
import pytest

from xtouch_daemon.audio import pulse as pulse_module
from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Card, Direction, Profile
from xtouch_daemon.audio.pulse import (
    PA_INVALID_INDEX,
    PulseBackend,
    balance_of,
    balanced_volume,
    follow_state,
    scaled_volume,
)

# what pulsectl reports (its enum has its values as dynamic attributes)
RUNNING = pulsectl.PulseStateEnum["running"]
SUSPENDED = pulsectl.PulseStateEnum["suspended"]


def volume(*values: float) -> SimpleNamespace:
    return SimpleNamespace(values=list(values))


def sink(
    index: int,
    name: str,
    description: str = "",
    state: Any = SUSPENDED,
    values=(0.5, 0.5),
    mute=0,
    card=PA_INVALID_INDEX,
    channels: tuple[str, ...] | None = None,
):
    # a channel for each volume
    if channels is None:
        channels = ("front-left", "front-right")[: len(values)]
    return SimpleNamespace(
        index=index,
        name=name,
        description=description,
        state=state,
        volume=volume(*values),
        mute=mute,
        card=card,
        channel_list=list(channels),
    )


def profile(name: str, description: str = "") -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description)


def card(index: int, name: str, active: str, *profiles: SimpleNamespace, description: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        name=name,
        proplist={"device.description": description} if description else {},
        profile_list=list(profiles),
        profile_active=next(p for p in profiles if p.name == active),
    )


def source(index: int, name: str, monitor_of_sink: int | None = PA_INVALID_INDEX, state: Any = SUSPENDED):
    info = sink(index, name, name.upper(), state)
    info.monitor_of_sink = monitor_of_sink
    return info


def sink_input(index: int, properties: dict[str, str], name: str = "", corked=0, values=(0.6, 0.6), mute=0):
    return SimpleNamespace(
        index=index,
        name=name,
        proplist=properties,
        corked=corked,
        volume=volume(*values),
        mute=mute,
        channel_list=["front-left", "front-right"][: len(values)],
    )


def source_output(index: int, source: int, properties: dict[str, str], name: str = "", corked=0):
    return SimpleNamespace(index=index, source=source, name=name, proplist=properties, corked=corked)


class FakePulse:
    """The parts of pulsectl_asyncio.PulseAsync the backend uses."""

    def __init__(self) -> None:
        self.server = SimpleNamespace(default_sink_name="speaker", default_source_name="mic")
        self.sinks = [
            sink(1, "speaker", "Speaker", RUNNING, card=30),
            sink(2, "buds", "", values=(0.8, 0.4), mute=1),
        ]
        self.cards = [
            card(
                30,
                "onboard",
                "analog",
                profile("analog", "Analog Output"),
                profile("digital", "Digital Output"),
                description="Onboard Audio",
            ),
            # without a description it is the name
            card(31, "usb", "off", profile("off")),
        ]
        self.sources = [
            source(3, "speaker.monitor", monitor_of_sink=1),
            source(4, "mic"),
            source(5, "old", None),
            source(6, "gone.monitor", monitor_of_sink=9),
        ]
        self.sink_inputs = [
            sink_input(
                10,
                {"application.name": "Brave", "application.process.binary": "brave", "application.process.id": "42"},
                values=(0.6, 0.3),
            ),
            sink_input(11, {"application.process.binary": "mpv"}, corked=1),
            sink_input(12, {}, name="stream name"),
            sink_input(13, {}),
        ]
        self.source_outputs = [
            source_output(20, 4, {"application.name": "WEBRTC VoiceEngine", "application.process.binary": "Discord"}),
            source_output(21, 3, {"application.process.binary": "obs"}, corked=1),
            # what a capture of something else than a device records is not known
            source_output(22, PA_INVALID_INDEX, {}, name="per stream"),
            # the monitor of an output that is gone
            source_output(23, 6, {"application.name": "recorder"}),
            # level meters (pavucontrol's, the daemon's own) don't count
            source_output(24, 4, {"media.name": "Peak detect", "stream.monitor": "true"}),
            source_output(25, 4, {"application.name": "xtouch-daemon", "node.passive": "true"}),
        ]
        self.events: asyncio.Queue[object] = asyncio.Queue()
        self.calls: list[tuple[str, Any, Any]] = []
        self.fail: BaseException | None = None
        self.snapshots = 0

    async def __aenter__(self) -> FakePulse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def server_info(self) -> Any:
        self.snapshots += 1
        return self.server

    async def sink_list(self) -> list[Any]:
        return self.sinks

    async def source_list(self) -> list[Any]:
        return self.sources

    async def sink_input_list(self) -> list[Any]:
        return self.sink_inputs

    async def source_output_list(self) -> list[Any]:
        return self.source_outputs

    async def card_list(self) -> list[Any]:
        return self.cards

    async def get_card_by_name(self, name: str) -> Any:
        return self._find(self.cards, name)

    async def card_profile_set(self, card: Any, profile: str) -> None:
        if profile not in [p.name for p in card.profile_list]:
            raise pulsectl.PulseIndexError(profile)
        self.calls.append(("profile", card.name, profile))

    async def subscribe_events(self, *facilities: str) -> AsyncIterator[object]:
        while True:
            event = await self.events.get()
            if isinstance(event, BaseException):
                raise event
            if event is None:
                return
            yield event

    def _find(self, items: list[Any], name: str) -> Any:
        if self.fail is not None:
            raise self.fail
        for item in items:
            if item.name == name:
                return item
        raise pulsectl.PulseIndexError(name)

    async def get_sink_by_name(self, name: str) -> Any:
        return self._find(self.sinks, name)

    async def get_source_by_name(self, name: str) -> Any:
        return self._find(self.sources, name)

    async def sink_input_info(self, index: int) -> Any:
        if self.fail is not None:
            raise self.fail
        for item in self.sink_inputs:
            if item.index == index:
                return item
        raise pulsectl.PulseIndexError(index)

    async def volume_set(self, obj: Any, value: Any) -> None:
        self.calls.append(("volume", obj.name or obj.index, list(value.values)))

    async def mute(self, obj: Any, muted: bool) -> None:
        self.calls.append(("mute", obj.name or obj.index, muted))

    async def default_set(self, obj: Any) -> None:
        if obj.name == "broken":
            raise pulsectl.PulseOperationFailed(obj.index)
        self.calls.append(("default", obj.name, None))


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pulse_module, "RECONNECT_DELAY", 0.01)
    monkeypatch.setattr(pulse_module, "SETTLE_DELAY", 0.0)


async def test_a_snapshot_maps_devices_streams_and_defaults():
    state = await PulseBackend.snapshot(FakePulse())

    assert [(d.name, d.description, d.volume, d.muted, d.running) for d in state.outputs] == [
        ("speaker", "Speaker", 50, False, True),
        # without a description it is the name, the loudest channel is the volume
        ("buds", "buds", 80, True, False),
    ]
    # the monitor of an output is not an input
    assert [d.name for d in state.inputs] == ["mic", "old"]
    assert all(d.direction == Direction.INPUT for d in state.inputs)
    assert [(s.balance, s.pid) for s in state.streams][:2] == [(-0.5, 42), (0.0, None)]
    assert state.outputs[0].balance == 0.0
    # the volume not rounded, for the gain of the meters; a muted device has none
    assert [(d.fraction, d.gain) for d in state.outputs] == [(0.5, 0.125), (0.8, 0.0)]
    assert state.streams[0].fraction == 0.6
    assert [(s.index, s.app, s.binary, s.volume, s.corked) for s in state.streams] == [
        (10, "Brave", "brave", 60, False),
        (11, "mpv", "mpv", 60, True),
        (12, "stream name", "", 60, False),
        (13, "#13", "", 60, False),
    ]
    assert [(c.index, c.app, c.binary, c.device, c.direction, c.corked) for c in state.captures] == [
        (20, "WEBRTC VoiceEngine", "Discord", "mic", Direction.INPUT, False),
        (21, "obs", "obs", "speaker", Direction.OUTPUT, True),
        (22, "per stream", "", None, None, False),
        (23, "recorder", "", None, None, False),
    ]
    assert state.default_output == "speaker"
    assert state.default_input == "mic"
    assert state.connected
    assert [d.card for d in state.outputs] == ["onboard", None]
    assert state.cards == (
        Card(
            "onboard",
            "analog",
            (Profile("analog", "Analog Output"), Profile("digital", "Digital Output")),
            "Onboard Audio",
        ),
        Card("usb", "off", (Profile("off", "off"),)),
    )


async def test_a_snapshot_without_defaults_or_channels():
    fake = FakePulse()
    fake.server = SimpleNamespace(default_sink_name="", default_source_name=None)
    fake.sinks = [sink(1, "speaker", values=())]
    state = await PulseBackend.snapshot(fake)
    assert state.default_output is None
    assert state.default_input is None
    assert state.outputs[0].volume == 0
    assert state.outputs[0].fraction is None


def test_a_volume_keeps_the_balance_between_the_channels():
    assert scaled_volume([0.8, 0.4], 50) == pytest.approx([0.5, 0.25])
    assert scaled_volume([0.0, 0.0], 30) == pytest.approx([0.3, 0.3])
    assert scaled_volume([1.0], -5) == [0.0]
    assert scaled_volume([], 40) == []


async def wait_for(condition: Callable[[], bool]) -> None:
    for _ in range(1000):
        if condition():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("the condition did not come true")


async def test_follows_the_sound_server_and_takes_a_snapshot_after_events():
    fake = FakePulse()
    backend = PulseBackend(lambda name: fake)
    states: list[AudioState] = []
    task = asyncio.create_task(backend.run(states.append))
    await wait_for(lambda: len(states) == 1)

    fake.sink_inputs = []
    # a burst of events
    fake.events.put_nowait("sink_input remove")
    fake.events.put_nowait("server change")
    await wait_for(lambda: len(states) >= 2)
    assert states[-1].streams == ()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_lost_connection_is_reported_and_made_again():
    connections: list[FakePulse] = []

    def factory(name: str) -> FakePulse:
        assert name == "xtouch-daemon"
        if len(connections) == 1:
            connections.append(FakePulse())
            # the sound server is not there yet on the second try
            raise pulsectl.PulseError("connection refused")
        connections.append(FakePulse())
        return connections[-1]

    backend = PulseBackend(factory)
    states: list[AudioState] = []
    task = asyncio.create_task(backend.run(states.append))
    await wait_for(lambda: len(states) == 1)
    assert states[0].connected

    # the connection is lost: pulsectl raises PulseDisconnected, which is not a PulseError
    connections[0].events.put_nowait(pulsectl.PulseDisconnected())
    await wait_for(lambda: len(states) >= 4)
    assert states[1] is DISCONNECTED
    assert states[2] is DISCONNECTED
    assert states[3].connected
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_an_ended_subscription_counts_as_a_lost_connection():
    fake = FakePulse()
    calls = 0

    def factory(name: str) -> FakePulse:
        nonlocal calls
        calls += 1
        return fake

    backend = PulseBackend(factory)
    states: list[AudioState] = []
    task = asyncio.create_task(backend.run(states.append))
    await wait_for(lambda: len(states) == 1)
    fake.events.put_nowait(None)
    await wait_for(lambda: calls >= 2)
    assert DISCONNECTED in states
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_sound_server_that_is_not_there_is_only_logged_once(caplog: pytest.LogCaptureFixture):
    attempts = 0

    def factory(name: str) -> FakePulse:
        nonlocal attempts
        attempts += 1
        raise OSError("no socket")

    backend = PulseBackend(factory)
    states: list[AudioState] = []
    task = asyncio.create_task(backend.run(states.append))
    await wait_for(lambda: attempts >= 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(state is DISCONNECTED for state in states)
    assert sum("Lost the sound server" in record.message for record in caplog.records) == 1


async def connected_backend() -> tuple[PulseBackend, FakePulse, asyncio.Task[None]]:
    fake = FakePulse()
    backend = PulseBackend(lambda name: fake)
    states: list[AudioState] = []
    task = asyncio.create_task(backend.run(states.append))
    await wait_for(lambda: len(states) == 1)
    return backend, fake, task


async def test_carries_out_the_commands_of_the_strips():
    backend, fake, task = await connected_backend()

    await backend.set_device_volume(Direction.OUTPUT, "buds", 40)
    await backend.set_device_mute(Direction.INPUT, "mic", True)
    await backend.set_default(Direction.OUTPUT, "buds")
    await backend.set_default(Direction.INPUT, "mic")
    await backend.set_stream_volume(10, 30)
    await backend.set_stream_mute(10, False)
    await backend.set_card_profile("onboard", "digital")
    await backend.set_device_balance(Direction.OUTPUT, "speaker", 0.5)
    await backend.set_stream_balance(10, -1.0)

    assert fake.calls[6] == ("profile", "onboard", "digital")
    assert fake.calls[7][:2] == ("volume", "speaker")
    assert fake.calls[7][2] == pytest.approx([0.25, 0.5])
    assert fake.calls[8][:2] == ("volume", 10)
    assert fake.calls[8][2] == pytest.approx([0.6, 0.0])
    assert fake.calls[0][:2] == ("volume", "buds")
    assert fake.calls[0][2] == pytest.approx([0.4, 0.2])
    assert fake.calls[1:4] == [("mute", "mic", True), ("default", "buds", None), ("default", "mic", None)]
    assert fake.calls[4][:2] == ("volume", 10)
    assert fake.calls[4][2] == pytest.approx([0.3, 0.15])
    assert fake.calls[5] == ("mute", 10, False)
    task.cancel()


async def test_commands_that_can_not_be_carried_out_raise_a_command_error():
    backend, fake, task = await connected_backend()

    with pytest.raises(AudioCommandError, match="no output 'gone'"):
        await backend.set_device_volume(Direction.OUTPUT, "gone", 40)
    with pytest.raises(AudioCommandError, match="no stream #99"):
        await backend.set_stream_mute(99, True)
    fake.sinks.append(sink(7, "broken"))
    with pytest.raises(AudioCommandError, match="making broken the default failed"):
        await backend.set_default(Direction.OUTPUT, "broken")
    with pytest.raises(AudioCommandError, match="switching onboard to surround failed"):
        await backend.set_card_profile("onboard", "surround")
    with pytest.raises(AudioCommandError, match="no card 'gone'"):
        await backend.set_card_profile("gone", "analog")
    # a connection lost in the middle of a command
    fake.fail = pulsectl.PulseDisconnected()
    with pytest.raises(AudioCommandError):
        await backend.set_device_mute(Direction.OUTPUT, "speaker", True)
    with pytest.raises(AudioCommandError):
        await backend.set_stream_volume(10, 50)
    task.cancel()


async def test_commands_without_a_connection_raise_a_command_error():
    backend = PulseBackend(lambda name: FakePulse())
    with pytest.raises(AudioCommandError, match="not connected"):
        await backend.set_device_volume(Direction.OUTPUT, "speaker", 10)
    with pytest.raises(AudioCommandError, match="not connected"):
        await backend.set_stream_volume(10, 10)


def channels(*pairs: tuple[str, float]) -> SimpleNamespace:
    return SimpleNamespace(channel_list=[name for name, _ in pairs], volume=volume(*(value for _, value in pairs)))


@pytest.mark.parametrize(
    ("info", "balance"),
    [
        (channels(("front-left", 0.5), ("front-right", 0.5)), 0.0),
        (channels(("front-left", 0.5), ("front-right", 0.25)), -0.5),
        (channels(("front-left", 0.2), ("front-right", 0.8)), 0.75),
        (channels(("front-left", 0.0), ("front-right", 0.0)), 0.0),
        # the loudest channel of each side
        (channels(("front-left", 0.2), ("rear-left", 0.4), ("front-right", 0.4), ("lfe", 1.0)), 0.0),
        (channels(("mono", 0.5)), None),
        (SimpleNamespace(volume=volume(0.5, 0.5)), None),
    ],
)
def test_the_balance_is_like_pulseaudios(info: SimpleNamespace, balance: float | None):
    assert balance_of(info) == (pytest.approx(balance) if balance is not None else None)


def test_a_balance_turns_down_the_other_side_and_leaves_the_rest():
    info = channels(("front-left", 0.4), ("front-right", 0.8), ("lfe", 0.3))
    assert balanced_volume(info, 0.0) == pytest.approx([0.8, 0.8, 0.3])
    assert balanced_volume(info, -0.25) == pytest.approx([0.8, 0.6, 0.3])
    assert balanced_volume(info, 2.0) == pytest.approx([0.0, 0.8, 0.3])
    assert balanced_volume(channels(("mono", 0.5)), 0.5) == [0.5]


def test_volumes_go_above_where_the_sliders_of_pavucontrol_end() -> None:
    # pulsectl stops at 153 %; the strips go up to 200 %
    struct = pulse_module.Volume([2.0, 1.0]).to_struct()
    assert list(struct.values)[: struct.channels] == [2 * 65536, 65536]
    struct = pulse_module.Volume([1e9]).to_struct()
    assert struct.values[0] == pulsectl._pulsectl.PA_VOLUME_MAX


def test_follow_state_calls_back_with_each_state_until_the_callback_raises():
    fake = FakePulse()
    states: list[AudioState] = []

    class Enough(Exception):
        pass

    def on_state(state: AudioState) -> None:
        states.append(state)
        if len(states) == 1:
            fake.sink_inputs = []
            fake.events.put_nowait("sink_input remove")
        else:
            raise Enough

    with pytest.raises(Enough):
        follow_state("test", on_state, lambda name: fake)
    assert len(states) == 2
    assert states[-1].streams == ()
