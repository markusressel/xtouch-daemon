"""
The live view: the running daemon tells what the device shows right now (the LCDs, LEDs, rings, faders and meters),
so the GUI can show the strips as they are instead of what a file would make of them.

The daemon serves a Unix socket next to its runtime file (see `instance.socket_file()`). Every client gets the whole
state as one line of JSON when it connects, and again whenever something changed (`LiveServer.changed()`, no timer:
what moves by itself, a falling meter and a gliding fader, is told once and the GUI draws it moving). Whole
states rather than changes: a line is about 2 KB, and a client that missed one (or connects late) needs nothing else
to be right. A client that does not keep up is dropped instead of being waited for, so a stuck GUI never slows down
the daemon.

A client of the same user may also send requests, a line of JSON each: the live preview of the GUI (`StartPreview`,
`KeepPreview`, `EndPreview`), a mode picked (`SetMode`), the override of a state (`SetOverride`) and the log of the
daemon (`WatchLog`, `EndLog`). The daemon
answers with `Reply` lines, which have no `version`: a GUI that does not know replies ignores them like lines of
another version, and an older daemon ignores the requests.

- `messages`: the snapshots, requests and replies.
- `codec`: them as lines of JSON.
- `server`: the socket of the daemon, and the snapshot of a surface.
- `log`: the records of the log the daemon keeps for the GUI.
"""
