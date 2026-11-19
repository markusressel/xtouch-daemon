# Design: the log in the GUI

Status: built (2026-11-19).

## Problem

The log of the daemon is where it says why: why it did not take the file, why the broker is gone, which device it
waits for. To read it, one has to know where it goes: the journal for the service (`journalctl --user -u
xtouch-daemon -f`), the terminal or the IDE for a daemon started by hand. The GUI, where the questions come up, shows
none of it.

## Decisions

- **Over the live view, not from the journal.** The GUI already talks to the daemon over its socket
  ([Live view](../architecture/live-view.md)). Reading the journal would need `journalctl` or the systemd bindings in
  the GUI and would miss a daemon in a terminal; the socket works for both, and needs nothing new on the machine.
- **A ring buffer in the daemon.** A `logging.Handler` (`live/log.LogBuffer`) keeps the latest 1000 records (about
  150 KB), attached to the root logger by `xtouch-daemon run` before the configuration is read, so the window shows
  the start too. It keeps what the terminal or the journal get, at the daemon's `--log-level`: no second level, so a
  record costs the same as before, and the window and the journal agree.
- **Pushed while watched.** `WatchLog` gets the buffer in one line (`backlog`), then the new records, batched: one
  line per client each time the event loop gets to it, as for the snapshots. `EndLog` and the end of the connection
  stop it. The GUI watches only while the window Log shows.
- **Cheap without watchers.** The handler formats the message and appends it to a deque; nothing else runs until a
  client watches. With one, the handler calls back through `call_soon_threadsafe` (other threads log too), so the
  socket is only written from the event loop.
- **The server answers, not the daemon.** The log has nothing to do with the slots or the device. `LiveServer`
  handles `WatchLog` and `EndLog` (`LogRequest`) itself; `Daemon.on_request()` gets the others (`DaemonRequest`).
- **Versioned like the rest.** `log` in `FEATURES`. A GUI with an older daemon says "too old" instead of asking; an
  older GUI skips the lines `{"log": ...}` like any line without its version.
- **Records, not text.** A record has its `seq`, time, level, logger and message (with its traceback), so the GUI
  colors and filters by level without parsing text. `seq` counts from 1 in each daemon: a gap shows records that left
  the buffer before a slow client got them.
- **Of the user only**, like the requests: the log names files, devices and people. The daemon logs no secrets.

## The window

- A dock like the window Device, hidden at first: View → Log (Ctrl+L). It can be a window of its own.
- Colors of the theme by level: debug muted, warning and error in their colors, critical bold; the time muted.
- The level filter shows a level and above, Debug at first: the daemon decides how much it logs.
- The search marks every match (ignoring case) and counts them; Enter selects the next one. At most 1000 are marked.
- Follow keeps the end in view; scrolling up stops it, scrolling to the end starts it again.
- It keeps the latest 5000 records. A backlog starts it over: the window opens again, or the daemon restarted. When
  the daemon goes away, the last records stay with a note, so the reason of a crash can be read.

## Not done

- A history beyond the buffer (the journal has it), and saving the log to a file (select and copy works).
- A level of its own for the window (e.g. debug records for the GUI while the journal gets info): it would make
  every debug call cost a record.
