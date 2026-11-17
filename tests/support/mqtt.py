"""An MQTT broker in memory, with clients shaped like `aiomqtt.Client`: retained messages, subscriptions, last wills."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Self

import aiomqtt


@dataclass(frozen=True)
class Message:
    topic: str
    payload: bytes
    retain: bool


class FakeBroker:
    def __init__(self) -> None:
        self.retained: dict[str, str] = {}
        self.published: list[tuple[str, str, bool]] = []
        """Everything any client published: (topic, payload, retain)."""
        self.clients: list[FakeClient] = []
        self.refuse = 0
        """How many of the next connections fail."""

    def client(self, **options: Any) -> FakeClient:
        client = FakeClient(self, options)
        self.clients.append(client)
        return client

    @property
    def connected(self) -> list[FakeClient]:
        return [client for client in self.clients if client.connected]

    def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        """What another client (e.g. Home Assistant) publishes."""
        self.published.append((topic, payload, retain))
        if retain:
            if payload:
                self.retained[topic] = payload
            else:
                self.retained.pop(topic, None)
        for client in self.connected:
            if topic in client.subscriptions:
                client.queue.put_nowait(Message(topic, payload.encode(), retain=False))

    def disconnect(self) -> None:
        """The connection of every client breaks: their last wills are published."""
        for client in self.connected:
            client.queue.put_nowait(None)

    def last(self, topic: str) -> str | None:
        """The payload last published on the topic."""
        return next((payload for t, payload, _ in reversed(self.published) if t == topic), None)


class FakeClient:
    def __init__(self, broker: FakeBroker, options: dict[str, Any]) -> None:
        self.broker = broker
        self.options = options
        self.subscriptions: set[str] = set()
        self.queue: asyncio.Queue[Message | None] = asyncio.Queue()
        self.connected = False
        self.fail_publish = False
        self.unsubscribe_gate: asyncio.Event | None = None
        """Holds unsubscribes until it is set, like a broker that is slow to acknowledge."""

    async def __aenter__(self) -> Self:
        if self.broker.refuse:
            self.broker.refuse -= 1
            raise aiomqtt.MqttError("Connection refused")
        self.connected = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any, /) -> None:
        self.connected = False
        will: aiomqtt.Will | None = self.options.get("will")
        if exc_type is not None and will is not None:
            self.broker.publish(will.topic, str(will.payload), will.retain)

    @property
    def messages(self) -> AsyncIterator[aiomqtt.Message]:
        return self._messages()  # type: ignore[return-value]

    async def _messages(self) -> AsyncIterator[Message]:
        while True:
            message = await self.queue.get()
            if message is None:
                raise aiomqtt.MqttError("Disconnected during message iteration")
            yield message

    async def publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
        if self.fail_publish:
            raise aiomqtt.MqttError("Operation timed out")
        self.broker.publish(topic, payload, retain)

    async def subscribe(self, topic: str) -> None:
        self.subscriptions.add(topic)
        if topic in self.broker.retained:
            self.queue.put_nowait(Message(topic, self.broker.retained[topic].encode(), retain=True))

    async def unsubscribe(self, topic: str) -> None:
        if self.unsubscribe_gate is not None:
            await self.unsubscribe_gate.wait()
        self.subscriptions.discard(topic)
