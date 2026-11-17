"""
Picking the mode of the running daemon (`mode`), over the socket of its live view; `layout` points to it.
"""

import socket
from collections.abc import Iterator
from typing import BinaryIO

import click

from xtouch_daemon.live.codec import decode_message, encode_request
from xtouch_daemon.live.messages import Reply, SetMode, Snapshot
from xtouch_daemon.system import instance

TIMEOUT = 3.0
"""Seconds `mode` waits for the daemon."""


def _live_lines(lines: BinaryIO) -> Iterator[Snapshot | Reply]:
    """The snapshots and replies of the live view, until the daemon closes the connection."""
    for line in lines:
        message = decode_message(line)
        if message is not None:
            yield message


@click.command(hidden=True, context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def layout(args: tuple[str, ...]) -> None:
    """Layouts are gone: `mode` lists and picks the modes."""
    raise click.ClickException("layouts are gone: `xtouch-daemon mode` lists and picks the modes")


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
        try:
            current = next(message for message in messages if isinstance(message, Snapshot))
        except (StopIteration, TimeoutError) as e:
            raise click.ClickException("the daemon did not answer") from e
        slots = current.slots
        if slots is None:
            raise click.ClickException("the daemon is older than this program, restart it")
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
