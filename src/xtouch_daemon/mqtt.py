"""
The connection to the MQTT broker of Home Assistant, for `homeassistant` strips: it announces their entities by MQTT
discovery, passes the commands of Home Assistant to them and publishes their states.

The entities are those of haad-mqtt-autodiscovery, and work as in haad: a state is published (retained), and only
the copy that comes back from the broker changes the entity. So after a (re)connect, the retained states restore
what Home Assistant set last; entities that have none yet get their default.
"""

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Protocol, Self

import aiomqtt
from haad_mqtt_autodiscovery import MQTTDevice
from haad_mqtt_autodiscovery.entity import MQTTEntity

from xtouch_daemon import __version__
from xtouch_daemon.config import MqttConfig

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 5.0
ONLINE = "online"
OFFLINE = "offline"

type Watcher = Callable[[MQTTEntity], None]


class MqttClient(Protocol):
    """The parts of `aiomqtt.Client` the bridge uses."""

    @property
    def messages(self) -> AsyncIterator[aiomqtt.Message]: ...

    async def __aenter__(self) -> Self: ...

    def __aexit__(self, exc_type: Any, exc: Any, tb: Any, /) -> Awaitable[Any]: ...

    def publish(self, topic: str, payload: str, *, retain: bool = False) -> Awaitable[None]: ...

    def subscribe(self, topic: str) -> Awaitable[Any]: ...

    def unsubscribe(self, topic: str) -> Awaitable[Any]: ...


type ClientFactory = Callable[..., MqttClient]


class MqttBridge:
    """
    Implements haad-mqtt-autodiscovery's `MQTTManagerProtocol`. `set_entities()` gives it the entities of the current
    configuration with their defaults; `watch()` calls back when an entity changed (also for the retained state on
    connect, unlike the entities' own listeners).
    """

    def __init__(self, config: MqttConfig, client_factory: ClientFactory = aiomqtt.Client):
        self.config = config
        # resolved now, so a missing password file stops the daemon right away
        self._password = config.resolve_password()
        self._client_factory = client_factory
        self._client: MqttClient | None = None
        self._entities: dict[str, tuple[MQTTEntity, str | None]] = {}
        self._watchers: dict[str, Watcher] = {}
        self._handlers: dict[str, Callable[[str, bool], Any]] = {}
        self._available = False
        self._sync_token: str | None = None
        self.ready = False
        """Connected, and the retained states are in: what the entities show is what Home Assistant set."""
        self.on_connection: Callable[[bool], None] = lambda connected: None
        self.device = MQTTDevice(
            identifiers=[f"xtouch_daemon_{config.namespace}"],
            name=config.device_name,
            manufacturer="Behringer",
            model=f"X-Touch Extender (xtouch-daemon {__version__})",
        )

    @property
    def availability_topic(self) -> str:
        return f"xtouch-daemon/{self.config.namespace}/availability"

    @property
    def sync_topic(self) -> str:
        return f"xtouch-daemon/{self.config.namespace}/sync"

    @property
    def connected(self) -> bool:
        return self._client is not None

    # -- the entities ---------------------------------------------------------------------------------------------

    def watch(self, entity: MQTTEntity, watcher: Watcher) -> None:
        self._watchers[entity.unique_id] = watcher

    def unwatch(self, entity: MQTTEntity) -> None:
        self._watchers.pop(entity.unique_id, None)

    async def set_entities(self, entities: Mapping[MQTTEntity, str | None]) -> None:
        """
        The entities of the configuration, with the state each gets while it has none (None: no default). Entities
        that are not there anymore are removed from Home Assistant.
        """
        previous = self._entities
        self._entities = {entity.unique_id: (entity, default) for entity, default in entities.items()}
        for entity, _ in self._entities.values():
            entity.discovery_prefix = self.config.discovery_prefix
            entity.bind_manager(self)
        if self._client is None:
            return
        for unique_id, (entity, _) in previous.items():
            await self._forget(self._client, entity, removed=unique_id not in self._entities)
        await self._announce(self._client)

    async def set_state(self, entity: MQTTEntity, state: str) -> None:
        if self._client is None:
            _LOGGER.debug(f"Not connected, dropping the state of {entity.entity_id}")
            return
        try:
            await self._client.publish(entity.state_topic, state, retain=entity.retain_state)
        except aiomqtt.MqttError as e:
            # the connection is gone: run() notices and connects again
            _LOGGER.debug(f"Can't publish the state of {entity.entity_id}: {e}")

    async def set_attributes(self, entity: MQTTEntity, attributes: str) -> None:
        if self._client is None:
            return
        await self._client.publish(entity.json_attributes_topic, attributes, retain=True)

    async def set_available(self, available: bool) -> None:
        """Whether the entities can be used (the device is connected); Home Assistant greys them out otherwise."""
        self._available = available
        if self._client is not None:
            await self._client.publish(self.availability_topic, ONLINE if available else OFFLINE, retain=True)

    # -- the connection -------------------------------------------------------------------------------------------

    async def run(self) -> None:
        was_connected = True
        will = aiomqtt.Will(self.availability_topic, OFFLINE, retain=True)
        while True:
            try:
                async with self._client_factory(
                    hostname=self.config.host,
                    port=self.config.port,
                    username=self.config.username,
                    password=self._password,
                    identifier=f"xtouch-daemon-{self.config.namespace}-{uuid.uuid4().hex[:8]}",
                    will=will,
                ) as client:
                    _LOGGER.info(f"Connected to the MQTT broker {self.config.host}:{self.config.port}")
                    was_connected = True
                    await self._follow(client)
            except aiomqtt.MqttError as e:
                if was_connected:
                    _LOGGER.warning(f"Lost the MQTT broker ({e}), connecting again every {RECONNECT_DELAY:.0f}s")
                was_connected = False
            finally:
                if self._client is not None:
                    self._client = None
                    self.ready = False
                    self.on_connection(False)
            await asyncio.sleep(RECONNECT_DELAY)

    async def _follow(self, client: MqttClient) -> None:
        self._client = client
        await client.subscribe(self.sync_topic)
        await client.publish(self.availability_topic, ONLINE if self._available else OFFLINE, retain=True)
        await self._announce(client)
        self.on_connection(True)
        async for message in client.messages:
            await self._handle(str(message.topic), message.payload.decode(), bool(message.retain))

    async def close(self) -> None:
        """Marks the entities unavailable (the broker would only do so later, by the last will)."""
        if self._client is not None:
            with contextlib.suppress(aiomqtt.MqttError):
                await self._client.publish(self.availability_topic, OFFLINE, retain=True)

    async def _announce(self, client: MqttClient) -> None:
        """Publishes the discovery of every entity, subscribes to its topics, then waits for the retained states."""
        self._handlers = {}
        for entity, _ in self._entities.values():
            await client.publish(entity.config_topic, json.dumps(self._discovery(entity)), retain=True)
            command_topic = getattr(entity, "command_topic", None)
            if command_topic is not None:
                self._handlers[command_topic] = self._command_handler(entity)
                await client.subscribe(command_topic)
            if entity.retain_state:
                self._handlers[entity.state_topic] = self._state_handler(entity)
                await client.subscribe(entity.state_topic)
        # the broker sends the retained states before what is published after the subscriptions
        self.ready = False
        self._sync_token = uuid.uuid4().hex
        await client.publish(self.sync_topic, self._sync_token)

    async def _forget(self, client: MqttClient, entity: MQTTEntity, removed: bool) -> None:
        command_topic = getattr(entity, "command_topic", None)
        if command_topic is not None:
            await client.unsubscribe(command_topic)
        if entity.retain_state:
            await client.unsubscribe(entity.state_topic)
        if removed:
            # an empty configuration removes the entity from Home Assistant
            await client.publish(entity.config_topic, "", retain=True)

    def _discovery(self, entity: MQTTEntity) -> dict[str, Any]:
        payload = entity.get_discovery_payload().to_json()
        payload["availability_topic"] = self.availability_topic
        payload["origin"] = {"name": "xtouch-daemon", "sw_version": __version__}
        return payload

    def _command_handler(self, entity: MQTTEntity) -> Callable[[str, bool], Any]:
        async def handle(payload: str, retain: bool) -> None:
            await entity.handle_command(payload)  # pyright: ignore[reportAttributeAccessIssue]

        return handle

    def _state_handler(self, entity: MQTTEntity) -> Callable[[str, bool], Any]:
        async def handle(payload: str, retain: bool) -> None:
            await entity.handle_state_sync(payload, retain)
            watcher = self._watchers.get(entity.unique_id)
            if watcher is not None:
                watcher(entity)

        return handle

    async def _handle(self, topic: str, payload: str, retain: bool) -> None:
        if topic == self.sync_topic:
            if payload == self._sync_token:
                await self._seed()
            return
        handler = self._handlers.get(topic)
        if handler is None:
            return
        try:
            await handler(payload, retain)
        except Exception:
            _LOGGER.exception(f"Handling {payload!r} on {topic}")

    async def _seed(self) -> None:
        """Gives the entities without a retained state their default, then tells the strips everything is in."""
        for entity, default in self._entities.values():
            if entity.state is None and default is not None:
                await entity._publish_state(default)  # pyright: ignore[reportPrivateUsage]
        self.ready = True
        for entity, _ in self._entities.values():
            watcher = self._watchers.get(entity.unique_id)
            if watcher is not None:
                watcher(entity)
