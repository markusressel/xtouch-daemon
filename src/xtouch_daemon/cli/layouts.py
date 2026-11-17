"""
Switching the layout (`layout`) or the mode (`mode`) of the running daemon, over the socket of its live view.
"""

import socket
from collections.abc import Iterator
from typing import BinaryIO

import click

from xtouch_daemon.live.codec import decode_message, encode_request
from xtouch_daemon.live.messages import Reply, SetMode, Snapshot, SwitchLayout
from xtouch_daemon.system import instance

LAYOUT_TIMEOUT = 3.0
"""Seconds `layout` waits for the daemon to show the layout."""


def _live_lines(lines: BinaryIO) -> Iterator[Snapshot | Reply]:
    """The snapshots and replies of the live view, until the daemon closes the connection."""
    for line in lines:
        message = decode_message(line)
        if message is not None:
            yield message


@click.command()
@click.argument("name", required=False)
@click.option("--next", "step", flag_value=1, type=int, help="Switch to the next layout.")
@click.option("--previous", "step", flag_value=-1, type=int, help="Switch to the previous layout.")
def layout(name: str | None, step: int | None) -> None:
    """List the layouts of the running daemon, or switch it to the layout NAME (or the next or previous one)."""
    with _connect() as sock:
        _switch_layout(sock, name, step)


def _connect() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(LAYOUT_TIMEOUT)
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
            raise click.ClickException("the daemon runs strips and layouts: see `xtouch-daemon layout`")
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


def _switch_layout(sock: socket.socket, name: str | None, step: int | None) -> None:
    with sock.makefile("rb") as lines:
        messages = _live_lines(lines)
        try:
            current = next(message for message in messages if isinstance(message, Snapshot))
        except (StopIteration, TimeoutError) as e:
            raise click.ClickException("the daemon did not answer") from e
        names = current.layouts or ("default",)
        if name is None and step is None:
            for each in names:
                click.echo(f"{'*' if each == current.layout else ' '} {each}")
            return
        if name is not None and name not in names:
            raise click.ClickException(f"there is no layout {name} ({', '.join(names)})")
        if current.slots is not None:
            click.echo("The daemon has modes: `xtouch-daemon mode` replaces `layout`", err=True)
        if "layout" not in current.features:
            raise click.ClickException("the daemon is older than this program, restart it")
        active = current.layout or names[0]
        wanted = name if name is not None else names[(names.index(active) + (step or 0)) % len(names)]
        sock.sendall(encode_request(SwitchLayout(wanted)))
        try:
            reply = next(message for message in messages if isinstance(message, Reply))
        except (StopIteration, TimeoutError) as e:
            raise click.ClickException(f"the daemon did not switch to {wanted}") from e
        if not reply.ok:
            raise click.ClickException(reply.message)
        click.echo(f"Layout {wanted}")
