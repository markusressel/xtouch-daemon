"""
The connection to the MQTT broker of Home Assistant, for the GUI: how the daemon's is doing (from its live view), and
a test of the settings in the editor before they are saved. The errors of the broker and of the network are put in
words that say what to check.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiomqtt

from xtouch_daemon.config.base import ConfigError
from xtouch_daemon.config.sections import MqttConfig
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.live.messages import MqttState, Snapshot

TEST_TIMEOUT = 5.0
"""Seconds a test waits for the broker."""
RETRY = "The daemon tries again every 5 seconds."


@dataclass(frozen=True)
class Explanation:
    short: str
    """A few words for a pill, e.g. "not authorized"."""
    hint: str
    """What to check."""


def explain(error: str) -> Explanation:
    """What an error of aiomqtt (the broker's reason code, or the error of the network) means."""
    lowered = error.lower()
    # MQTT 3.1.1 says "Bad username or password" and "Not authorised", MQTT 5 "Bad user name or password" and "Not
    # authorized"
    if "not authori" in lowered or "bad user" in lowered or "password" in lowered:
        return Explanation(
            "not authorized",
            "The broker does not accept the username and password: check `username` and the password (its file or "
            "environment variable), and that the user exists on the broker.",
        )
    if "refused" in lowered:
        return Explanation(
            "refused",
            "Nothing takes connections at the host and port: is the broker running, and is it the right port "
            "(1883 without TLS)?",
        )
    if "name or service not known" in lowered or "name resolution" in lowered or "nodename" in lowered:
        return Explanation("unknown host", "The host name does not resolve: check `host`.")
    if "timed out" in lowered or "timeout" in lowered or "no route" in lowered or "unreachable" in lowered:
        return Explanation("unreachable", "The host does not answer: check `host` and the network.")
    return Explanation(error, "")


def live_status(snapshot: Snapshot | None) -> Status:
    """How the daemon's connection to Home Assistant is doing, for the page of the [mqtt] section."""
    if snapshot is None:
        return Status(
            "unknown",
            Tone.NEUTRAL,
            "The daemon does not run, or gives no live view: once it runs, this tells how its connection is doing.",
        )
    if snapshot.mqtt is None:
        return Status(
            "not in use",
            Tone.WARN,
            "The daemon runs without an [mqtt] section: a new or changed one takes a restart of the service.",
        )
    state = snapshot.mqtt_state
    if state is None:
        # an older daemon: only whether it is connected
        if snapshot.mqtt:
            return Status("connected", Tone.GOOD, "The daemon is connected to the MQTT broker.")
        return Status("not connected", Tone.WARN, "The daemon is not connected to the MQTT broker.")
    return status_of(state)


def status_of(state: MqttState) -> Status:
    who = f" as {state.username}" if state.username else ""
    if state.connected and state.ready:
        return Status(
            "connected",
            Tone.GOOD,
            f"Connected to the MQTT broker {state.broker}{who}, {_entities(state.entities)} in Home Assistant.",
        )
    if state.connected:
        return Status(
            "syncing",
            Tone.NEUTRAL,
            f"Connected to {state.broker}{who}, reading what Home Assistant keeps for the entities.",
        )
    if state.error is None:
        return Status("connecting", Tone.WARN, f"Connecting to the MQTT broker {state.broker}{who}.")
    explanation = explain(state.error)
    return Status(
        explanation.short,
        Tone.BAD,
        " ".join(
            part
            for part in (
                f"Can't connect to the MQTT broker {state.broker}{who}: {state.error}.",
                explanation.hint,
                RETRY,
            )
            if part
        ),
    )


def _entities(count: int) -> str:
    return f"{count} entit{'y' if count == 1 else 'ies'}"


type ClientFactory = Callable[..., Any]


async def try_broker(config: MqttConfig, client_factory: ClientFactory = aiomqtt.Client) -> Status:
    """Connects with `config` once and disconnects again: whether the daemon could connect with it."""
    try:
        password = config.resolve_password()
    except ConfigError as e:
        return Status("Can't connect", Tone.BAD, str(e))
    who = f" as {config.username}" if config.username else ""
    broker = f"{config.host}:{config.port}"
    try:
        async with asyncio.timeout(TEST_TIMEOUT):
            async with client_factory(
                hostname=config.host,
                port=config.port,
                username=config.username,
                password=password,
                identifier=f"xtouch-daemon-gui-{uuid.uuid4().hex[:8]}",
            ):
                pass
    except TimeoutError:
        explanation = explain("timed out")
        return Status(f"Can't connect to {broker}: no answer in {TEST_TIMEOUT:g} s.", Tone.BAD, explanation.hint)
    except aiomqtt.MqttError as e:
        explanation = explain(str(e))
        return Status(f"Can't connect to {broker}{who}: {e}.", Tone.BAD, explanation.hint)
    return Status(f"Connected to {broker}{who}: these settings work.", Tone.GOOD)
