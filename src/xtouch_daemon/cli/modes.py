"""
Picking the mode of the running daemon (`mode`) and asking it why a slot or channel shows what it does (`why`), over
the socket of its live view.
"""

import socket
from collections.abc import Iterator
from typing import BinaryIO

import click

from xtouch_daemon.live.codec import decode_message, encode_request
from xtouch_daemon.live.messages import KnownDevices, LogLines, Reply, SetMode, SlotsState, Snapshot, TwinView
from xtouch_daemon.slots.why import why as explain
from xtouch_daemon.system import instance

TIMEOUT = 3.0
"""Seconds `mode` waits for the daemon."""


def _live_lines(lines: BinaryIO) -> Iterator[Snapshot | Reply | TwinView]:
    """The snapshots, replies and twin views of the live view, until the daemon closes the connection."""
    for line in lines:
        message = decode_message(line)
        # the devices the daemon remembers and its log are for the GUI
        if message is not None and not isinstance(message, KnownDevices | LogLines):
            yield message


def _slots(messages: Iterator[Snapshot | Reply | TwinView]) -> SlotsState:
    """The slots of the first snapshot of the daemon."""
    try:
        current = next(message for message in messages if isinstance(message, Snapshot))
    except (StopIteration, TimeoutError) as e:
        raise click.ClickException("the daemon did not answer") from e
    if current.slots is None:
        raise click.ClickException("the daemon is older than this program, restart it")
    return current.slots


def _connect() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.connect(str(instance.socket_file()))
    except OSError as e:
        sock.close()
        raise click.ClickException(f"the daemon does not run, or is older than this program ({e.strerror})") from e
    return sock


@click.command()
@click.argument("name", required=False)
@click.option("--next", "step", flag_value="+1", help="Switch to the next mode.")
@click.option("--previous", "step", flag_value="-1", help="Switch to the previous mode.")
def mode(name: str | None, step: str | None) -> None:
    """
    List the modes of the running daemon, or pick the mode NAME (or the next or previous one); `auto` lets the
    rules decide again.
    """
    with _connect() as sock, sock.makefile("rb") as lines:
        messages = _live_lines(lines)
        slots = _slots(messages)
        if name is None and step is None:
            modes = ("default", *(state.name for state in slots.states if state.mode))
            for each in modes:
                click.echo(f"{'*' if each == slots.mode else ' '} {each}")
            click.echo("picked by hand" if slots.mode_pick is not None else "picked by the rules")
            return
        sock.sendall(encode_request(SetMode(name or step or "")))
        try:
            reply = next(message for message in messages if isinstance(message, Reply))
        except (StopIteration, TimeoutError) as e:
            raise click.ClickException("the daemon did not pick the mode") from e
        if not reply.ok:
            raise click.ClickException(reply.message)
        click.echo(f"Mode {reply.message}")


@click.command()
@click.argument("target")
def why(target: str) -> None:
    """
    Why the running daemon shows on slot TARGET (a number, 1 for the leftmost one) what it shows, or why the
    channel TARGET (its id) is where it is.
    """
    with _connect() as sock, sock.makefile("rb") as lines:
        click.echo(explain(_slots(_live_lines(lines)), target))
