import asyncio
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import pulsectl
import pytest

from xtouch_daemon.audio import pulse as pulse_module
from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Direction
from xtouch_daemon.audio.pulse import PA_INVALID_INDEX, PulseBackend, scaled_volume

# what pulsectl reports (its enum has its values as dynamic attributes)
RUNNING = pulsectl.PulseStateEnum["running"]
SUSPENDED = pulsectl.PulseStateEnum["suspended"]


def volume(*values: float) -> SimpleNamespace:
    return SimpleNamespace(values=list(values))


def sink(index: int, name: str, description: str = "", state: Any = SUSPENDED, values=(0.5, 0.5), mute=0):
    return SimpleNamespace(
        index=index, name=name, description=description, state=state, volume=volume(*values), mute=mute
    )


def source(index: int, name: str, monitor_of_sink: int | None = PA_INVALID_INDEX, state: Any = SUSPENDED):
    info = sink(index, name, name.upper(), state)
    info.monitor_of_sink = monitor_of_sink
    return info


def sink_input(index: int, properties: dict[str, str], name: str = "", corked=0, values=(0.6, 0.6), mute=0):
    return SimpleNamespace(
        index=index, name=name, proplist=properties, corked=corked, volume=volume(*values), mute=mute
    )


class FakePulse:
    """The parts of pulsectl_asyncio.PulseAsync the backend uses."""

    def __init__(self) -> None:
        self.server = SimpleNamespace(default_sink_name="speaker", default_source_name="mic")
        self.sinks = [sink(1, "speaker", "Speaker", RUNNING), sink(2, "buds", "", values=(0.8, 0.4), mute=1)]
        self.sources = [source(3, "speaker.monitor", monitor_of_sink=1), source(4, "mic"), source(5, "old", None)]
        self.sink_inputs = [
            sink_input(10, {"application.name": "Brave", "application.process.binary": "brave"}),
            sink_input(11, {"application.process.binary": "mpv"}, corked=1),
            sink_input(12, {}, name="stream name"),
            sink_input(13, {}),
        ]
        self.events: asyncio.Queue[object] = asyncio.Queue()
        self.calls: list[tuple[str, Any, Any]] = []
        self.fail: BaseException | None = None
        self.snapshots = 0

    async def __aenter__(self) -> "FakePulse":
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
    assert [(s.index, s.app, s.binary, s.volume, s.corked) for s in state.streams] == [
        (10, "Brave", "brave", 60, False),
        (11, "mpv", "mpv", 60, True),
        (12, "stream name", "", 60, False),
        (13, "#13", "", 60, False),
    ]
    assert state.default_output == "speaker"
    assert state.default_input == "mic"
    assert state.connected


async def test_a_snapshot_without_defaults_or_channels():
    fake = FakePulse()
    fake.server = SimpleNamespace(default_sink_name="", default_source_name=None)
    fake.sinks = [sink(1, "speaker", values=())]
    state = await PulseBackend.snapshot(fake)
    assert state.default_output is None
    assert state.default_input is None
    assert state.outputs[0].volume == 0


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

    assert fake.calls[0][:2] == ("volume", "buds")
    assert fake.calls[0][2] == pytest.approx([0.4, 0.2])
    assert fake.calls[1:4] == [("mute", "mic", True), ("default", "buds", None), ("default", "mic", None)]
    assert fake.calls[4][:2] == ("volume", 10)
    assert fake.calls[4][2] == pytest.approx([0.3, 0.3])
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
