"""
The sound server through its PulseAudio interface (`pipewire-pulse` with PipeWire): one connection that follows every
change by events, and carries out the commands of the strips.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

import pulsectl
import pulsectl_asyncio

from xtouch_daemon.audio.backend import AudioCommandError
from xtouch_daemon.audio.model import DISCONNECTED, AudioState, Capture, Card, Device, Direction, Profile, Stream

_LOGGER = logging.getLogger(__name__)

CLIENT_NAME = "xtouch-daemon"
RECONNECT_DELAY = 2.0
SETTLE_DELAY = 0.02
"""Events come in bursts (a new stream changes the stream, its sink and the server): one snapshot after them."""
EVENT_FACILITIES = ("sink", "source", "sink_input", "source_output", "server", "card")

PA_INVALID_INDEX = 0xFFFFFFFF

PULSE_ERRORS = (pulsectl.PulseError, pulsectl.PulseDisconnected)
"""What pulsectl raises: `PulseDisconnected` (a lost connection) is not a `PulseError`."""


def _percent(volume: Any) -> int:
    values = list(volume.values)
    return round(max(values) * 100) if values else 0


def _state_running(state: Any) -> bool:
    return str(state).endswith("running") or state == "running"


def _sides(info: Any) -> tuple[list[int], list[int]]:
    """The indexes of the left and of the right channels."""
    names = list(getattr(info, "channel_list", None) or ())
    return [i for i, n in enumerate(names) if "left" in n], [i for i, n in enumerate(names) if "right" in n]


def balance_of(info: Any) -> float | None:
    """Like PulseAudio's `pa_cvolume_get_balance`: -1 only left .. 1 only right, None without both sides."""
    values = list(info.volume.values)
    left_channels, right_channels = _sides(info)
    if not left_channels or not right_channels:
        return None
    left = max(values[i] for i in left_channels)
    right = max(values[i] for i in right_channels)
    if left == right:
        return 0.0
    return 1 - left / right if right > left else -1 + right / left


def balanced_volume(info: Any, balance: float) -> list[float]:
    """The channel volumes for `balance`: the louder side keeps the volume, the other one is turned down."""
    values = list(info.volume.values)
    left_channels, right_channels = _sides(info)
    top = max((values[i] for i in left_channels + right_channels), default=0.0)
    balance = max(-1.0, min(1.0, balance))
    for i in left_channels:
        values[i] = top * (1 - max(0.0, balance))
    for i in right_channels:
        values[i] = top * (1 + min(0.0, balance))
    return values


def _device(info: Any, direction: Direction, cards: dict[int, str]) -> Device:
    return Device(
        name=info.name,
        description=info.description or info.name,
        direction=direction,
        volume=_percent(info.volume),
        muted=bool(info.mute),
        running=_state_running(info.state),
        card=cards.get(info.card),
        balance=balance_of(info),
    )


def _card(info: Any) -> Card:
    return Card(
        name=info.name,
        profile=info.profile_active.name,
        profiles=tuple(Profile(profile.name, profile.description or profile.name) for profile in info.profile_list),
    )


def _stream(info: Any) -> Stream:
    properties = info.proplist
    binary = properties.get("application.process.binary", "")
    return Stream(
        index=info.index,
        app=properties.get("application.name") or binary or info.name or f"#{info.index}",
        binary=binary,
        volume=_percent(info.volume),
        muted=bool(info.mute),
        corked=bool(info.corked),
        balance=balance_of(info),
        pid=int(pid) if (pid := properties.get("application.process.id", "")).isdigit() else None,
    )


def _is_passive(info: Any) -> bool:
    properties = info.proplist
    return properties.get("node.passive") == "true" or properties.get("stream.monitor") == "true"


def _capture(info: Any, targets: dict[int, tuple[str, Direction]]) -> Capture:
    properties = info.proplist
    binary = properties.get("application.process.binary", "")
    device, direction = targets.get(info.source, (None, None))
    return Capture(
        index=info.index,
        app=properties.get("application.name") or binary or info.name or f"#{info.index}",
        binary=binary,
        device=device,
        direction=direction,
        corked=bool(info.corked),
    )


def _is_monitor(source: Any) -> bool:
    return getattr(source, "monitor_of_sink", PA_INVALID_INDEX) not in (PA_INVALID_INDEX, None)


def scaled_volume(values: list[float], percent: int) -> list[float]:
    """The channel volumes for `percent`, keeping the balance between the channels: the loudest gets `percent`."""
    target = max(0, percent) / 100
    top = max(values, default=0.0)
    if top <= 0:
        return [target] * len(values)
    return [value / top * target for value in values]


type PulseFactory = Callable[[str], Any]


class PulseBackend:
    def __init__(self, pulse_factory: PulseFactory = pulsectl_asyncio.PulseAsync, client_name: str = CLIENT_NAME):
        self._factory = pulse_factory
        self._client_name = client_name
        self._pulse: Any = None

    async def run(self, on_state: Callable[[AudioState], None]) -> None:
        was_connected = True
        while True:
            try:
                async with self._factory(self._client_name) as pulse:
                    self._pulse = pulse
                    _LOGGER.info("Connected to the sound server")
                    was_connected = True
                    await self._follow(pulse, on_state)
            except (*PULSE_ERRORS, OSError) as e:
                if was_connected:
                    _LOGGER.warning(f"Lost the sound server ({e}), connecting again every {RECONNECT_DELAY:.0f}s")
                was_connected = False
            finally:
                self._pulse = None
            on_state(DISCONNECTED)
            await asyncio.sleep(RECONNECT_DELAY)

    async def _follow(self, pulse: Any, on_state: Callable[[AudioState], None]) -> None:
        changed = asyncio.Event()

        async def listen() -> None:
            try:
                async for _ in pulse.subscribe_events(*EVENT_FACILITIES):
                    changed.set()
            finally:
                # wakes the loop below, which then sees the listener ended
                changed.set()

        listener = asyncio.create_task(listen())
        try:
            on_state(await self.snapshot(pulse))
            while True:
                await changed.wait()
                if listener.done():
                    listener.result()
                    raise pulsectl.PulseDisconnected("the event subscription ended")
                await asyncio.sleep(SETTLE_DELAY)
                changed.clear()
                on_state(await self.snapshot(pulse))
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, *PULSE_ERRORS):
                await listener

    @staticmethod
    async def snapshot(pulse: Any) -> AudioState:
        server = await pulse.server_info()
        sinks = await pulse.sink_list()
        sources = await pulse.source_list()
        sink_inputs = await pulse.sink_input_list()
        source_outputs = await pulse.source_output_list()
        cards = await pulse.card_list()
        card_names = {card.index: card.name for card in cards}
        sink_names = {sink.index: sink.name for sink in sinks}
        # what a capture records: an input, or the monitor of an output
        targets = {
            source.index: (sink_names[source.monitor_of_sink], Direction.OUTPUT)
            if _is_monitor(source)
            else (source.name, Direction.INPUT)
            for source in sources
            if not _is_monitor(source) or source.monitor_of_sink in sink_names
        }
        return AudioState(
            outputs=tuple(_device(sink, Direction.OUTPUT, card_names) for sink in sinks),
            # the monitors of the outputs are sources too, they are not inputs
            inputs=tuple(_device(source, Direction.INPUT, card_names) for source in sources if not _is_monitor(source)),
            streams=tuple(_stream(sink_input) for sink_input in sink_inputs),
            captures=tuple(_capture(output, targets) for output in source_outputs if not _is_passive(output)),
            cards=tuple(_card(card) for card in cards),
            default_output=server.default_sink_name or None,
            default_input=server.default_source_name or None,
        )

    # -- commands -------------------------------------------------------------------------------------------------

    def _connected(self) -> Any:
        if self._pulse is None:
            raise AudioCommandError("not connected to the sound server")
        return self._pulse

    async def _device_info(self, direction: Direction, name: str) -> Any:
        pulse = self._connected()
        try:
            if direction == Direction.OUTPUT:
                return await pulse.get_sink_by_name(name)
            return await pulse.get_source_by_name(name)
        except PULSE_ERRORS as e:
            raise AudioCommandError(f"no {direction} {name!r}: {e}") from e

    async def _stream_info(self, index: int) -> Any:
        try:
            return await self._connected().sink_input_info(index)
        except PULSE_ERRORS as e:
            raise AudioCommandError(f"no stream #{index}: {e}") from e

    async def _call(self, what: str, call: Any) -> None:
        try:
            await call
        except PULSE_ERRORS as e:
            raise AudioCommandError(f"{what} failed: {e}") from e

    async def set_device_volume(self, direction: Direction, name: str, percent: int) -> None:
        info = await self._device_info(direction, name)
        volume = pulsectl.PulseVolumeInfo(scaled_volume(list(info.volume.values), percent))
        await self._call(f"setting the volume of {name}", self._connected().volume_set(info, volume))

    async def set_device_mute(self, direction: Direction, name: str, muted: bool) -> None:
        info = await self._device_info(direction, name)
        await self._call(f"muting {name}", self._connected().mute(info, muted))

    async def set_device_balance(self, direction: Direction, name: str, balance: float) -> None:
        info = await self._device_info(direction, name)
        volume = pulsectl.PulseVolumeInfo(balanced_volume(info, balance))
        await self._call(f"setting the balance of {name}", self._connected().volume_set(info, volume))

    async def set_default(self, direction: Direction, name: str) -> None:
        info = await self._device_info(direction, name)
        await self._call(f"making {name} the default", self._connected().default_set(info))

    async def set_stream_balance(self, index: int, balance: float) -> None:
        info = await self._stream_info(index)
        volume = pulsectl.PulseVolumeInfo(balanced_volume(info, balance))
        await self._call(f"setting the balance of stream #{index}", self._connected().volume_set(info, volume))

    async def set_card_profile(self, card: str, profile: str) -> None:
        pulse = self._connected()
        try:
            info = await pulse.get_card_by_name(card)
        except PULSE_ERRORS as e:
            raise AudioCommandError(f"no card {card!r}: {e}") from e
        await self._call(f"switching {card} to {profile}", pulse.card_profile_set(info, profile))

    async def set_stream_volume(self, index: int, percent: int) -> None:
        info = await self._stream_info(index)
        volume = pulsectl.PulseVolumeInfo(scaled_volume(list(info.volume.values), percent))
        await self._call(f"setting the volume of stream #{index}", self._connected().volume_set(info, volume))

    async def set_stream_mute(self, index: int, muted: bool) -> None:
        info = await self._stream_info(index)
        await self._call(f"muting stream #{index}", self._connected().mute(info, muted))


class SoundServerError(Exception):
    """The sound server could not be reached, with a message for the user."""


async def _read_state(client_name: str) -> AudioState:
    async with pulsectl_asyncio.PulseAsync(client_name) as pulse:
        return await PulseBackend.snapshot(pulse)


def read_state(client_name: str) -> AudioState:
    """The state of the sound server right now, from a connection of its own (for the tools around the daemon)."""
    try:
        return asyncio.run(_read_state(client_name))
    except Exception as e:
        raise SoundServerError(f"can't reach the sound server (is pipewire-pulse running?): {e}") from e
