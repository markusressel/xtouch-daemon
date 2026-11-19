"""
The log of the daemon over the live view (`WatchLog`): the records it keeps, and the new ones for the clients that
watch it.
"""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from tests.support.hardware import RecordingSurface
from tests.support.tasks import finish_tasks
from xtouch_daemon.live.codec import decode_message, decode_request, encode_log, encode_request
from xtouch_daemon.live.log import LogBuffer
from xtouch_daemon.live.messages import (
    EndLog,
    LogEntry,
    LogLines,
    Reply,
    Snapshot,
    WatchLog,
)
from xtouch_daemon.live.server import LiveServer, strip_states


@pytest.fixture(autouse=True)
async def no_tasks_left() -> AsyncIterator[None]:
    yield
    await finish_tasks()


@pytest.fixture
def logger() -> Iterator[logging.Logger]:
    result = logging.getLogger("tests.live.log")
    result.setLevel(logging.DEBUG)
    yield result
    result.setLevel(logging.NOTSET)


def snapshot_of(surface: RecordingSurface) -> Snapshot:
    return Snapshot("abc", device=True, sound_server=False, mqtt=None, strips=strip_states(surface, 0.0))


async def serve(server: LiveServer) -> asyncio.Task[None]:
    task = asyncio.create_task(server.run())
    for _ in range(100):
        if server.path.exists():
            return task
        await asyncio.sleep(0.005)
    raise AssertionError("the server did not start")


async def next_message(reader: asyncio.StreamReader, kind: type[LogLines] | type[Reply]) -> LogLines | Reply:
    """The next line of `kind`, past the snapshots."""
    while True:
        message = decode_message(await asyncio.wait_for(reader.readline(), 1))
        if isinstance(message, kind):
            return message


async def next_lines(reader: asyncio.StreamReader) -> LogLines:
    message = await next_message(reader, LogLines)
    assert isinstance(message, LogLines)
    return message


def messages(lines: LogLines) -> list[str]:
    return [entry.message for entry in lines.entries]


def test_the_buffer_keeps_the_latest_records(logger: logging.Logger):
    log = LogBuffer(size=2)
    with log.attached(logger):
        logger.debug("first")
        logger.info("second %s", "with arguments")
        try:
            raise RuntimeError("broken")
        except RuntimeError:
            logger.exception("third")
    # it is no longer attached
    logger.info("fourth")

    second, third = log.since(0)
    assert (second.seq, second.level, second.logger, second.message) == (
        2,
        "INFO",
        "tests.live.log",
        "second with arguments",
    )
    # with the traceback
    assert third.seq == 3
    assert third.level == "ERROR"
    assert third.message.startswith("third\nTraceback")
    assert "RuntimeError: broken" in third.message
    assert log.since(2) == (third,)
    assert log.last == 3


def test_a_record_that_can_not_be_formatted_is_skipped(logger: logging.Logger, monkeypatch: pytest.MonkeyPatch):
    # logging tells it on stderr otherwise
    monkeypatch.setattr(logging, "raiseExceptions", False)
    log = LogBuffer()
    with log.attached(logger):
        logger.info("%d apples", "no number")
        logger.info("fine")

    assert [entry.message for entry in log.since(0)] == ["fine"]


def test_the_root_logger_is_the_default(logger: logging.Logger):
    log = LogBuffer()
    with log.attached():
        assert log in logging.getLogger().handlers
        logger.warning("anything")
    assert log not in logging.getLogger().handlers
    assert log.since(0)[-1].message == "anything"


def test_the_log_and_its_requests_go_through_a_line():
    lines = LogLines((LogEntry(7, 1700000000.5, "WARNING", "xtouch_daemon.mqtt", "Lost the broker\nagain"),), True)
    line = encode_log(lines)
    assert line.count(b"\n") == 1
    assert decode_message(line) == lines
    assert decode_message(encode_log(LogLines(()))) == LogLines(())
    for request in (WatchLog(), EndLog()):
        assert decode_request(encode_request(request)) == request


async def test_a_client_that_watches_gets_the_kept_records_and_then_every_new_one(
    surface: RecordingSurface, socket_dir: Path, logger: logging.Logger
):
    log = LogBuffer(size=3)
    with log.attached(logger):
        for number in range(4):
            logger.info(f"before {number}")
        server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface), log=log)
        task = await serve(server)
        reader, writer = await asyncio.open_unix_connection(server.path)
        # nobody watches: a record costs nothing more
        assert log.on_entry is None

        writer.write(encode_request(WatchLog()))
        backlog = await next_lines(reader)
        assert backlog.backlog
        assert [entry.seq for entry in backlog.entries] == [2, 3, 4]
        assert messages(backlog) == ["before 1", "before 2", "before 3"]

        logger.info("new")
        logger.debug("and more")
        # what is logged together goes out together
        new = await next_lines(reader)
        assert not new.backlog
        assert messages(new) == ["new", "and more"]

        # another thread logs too
        thread = threading.Thread(target=lambda: logger.warning("from a thread"))
        thread.start()
        thread.join()
        assert messages(await next_lines(reader)) == ["from a thread"]

        writer.write(encode_request(EndLog()))
        await writer.drain()
        for _ in range(100):
            if log.on_entry is None:
                break
            await asyncio.sleep(0.005)
        assert log.on_entry is None
        logger.info("unseen")
        with pytest.raises(TimeoutError):
            await next_message(reader, LogLines)

        # watched again, from where the buffer is now
        writer.write(encode_request(WatchLog()))
        assert messages(await next_lines(reader)) == ["and more", "from a thread", "unseen"]
        # the connection ends: nobody watches
        writer.close()
        await writer.wait_closed()
        for _ in range(100):
            if log.on_entry is None:
                break
            await asyncio.sleep(0.005)
        assert log.on_entry is None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_an_empty_log_is_sent_too(surface: RecordingSurface, socket_dir: Path, logger: logging.Logger):
    log = LogBuffer()
    with log.attached(logger):
        server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface), log=log)
        task = await serve(server)
        reader, writer = await asyncio.open_unix_connection(server.path)

        writer.write(encode_request(WatchLog()))
        # the client knows that it watches
        assert await next_lines(reader) == LogLines((), backlog=True)
        logger.info("first")
        assert [entry.seq for entry in (await next_lines(reader)).entries] == [1]

        # the server stops: nobody watches
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert log.on_entry is None
        writer.close()


async def test_without_a_log_the_request_is_refused(surface: RecordingSurface, socket_dir: Path):
    server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface))
    task = await serve(server)
    reader, writer = await asyncio.open_unix_connection(server.path)

    writer.write(encode_request(WatchLog()) + encode_request(EndLog()))

    assert await next_message(reader, Reply) == Reply("error", False, "The daemon keeps no log")
    writer.close()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_each_watcher_gets_what_it_did_not_get_yet(
    surface: RecordingSurface, socket_dir: Path, logger: logging.Logger
):
    log = LogBuffer()
    with log.attached(logger):
        server = LiveServer(socket_dir / "live.sock", lambda: snapshot_of(surface), log=log)
        task = await serve(server)
        first_reader, first = await asyncio.open_unix_connection(server.path)
        second_reader, second = await asyncio.open_unix_connection(server.path)
        first.write(encode_request(WatchLog()))
        await next_lines(first_reader)
        logger.info("for the first")
        assert messages(await next_lines(first_reader)) == ["for the first"]
        second.write(encode_request(WatchLog()))
        assert messages(await next_lines(second_reader)) == ["for the first"]

        # the first one is done, the second one still watches
        first.write(encode_request(EndLog()))
        await first.drain()
        await asyncio.sleep(0.05)
        assert log.on_entry is not None
        logger.info("for the second")
        assert messages(await next_lines(second_reader)) == ["for the second"]
        # nothing new: nothing is sent
        server._publish_log()
        with pytest.raises(TimeoutError):
            await next_message(second_reader, LogLines)

        first.close()
        second.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
