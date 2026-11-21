# Design: what the daemon remembers

Status: built, with JSON files. SQLite was considered and not chosen (2026-11-21).

The daemon keeps a few things across restarts. They live in its state directory, `$XDG_STATE_HOME/xtouch-daemon`, by
default `~/.local/state/xtouch-daemon/` (`system/instance.py` `state_dir()`).

| File | Kept by | What |
|---|---|---|
| `slots.json` | `daemon/slot_files.py` | The overrides of states and the mode picked by hand. |
| `people.json` | `daemon/slot_files.py` | The order of the people. |
| `devices.json` | `daemon/device_memory.py` | The sound devices the daemon saw, for the GUI's suggestions. A device not seen for 90 days is forgotten. |

Together they are about 2 KB. A `layout` file there comes from the layouts that the slots replaced
([history](../history/layouts.md)); nothing reads it any more, and it can be deleted.

## How they are written

- Only the daemon writes them. The GUI asks the daemon over the [live view](../architecture/live-view.md).
- Each write goes to a temporary file, which then replaces the file. A crash leaves the old file or the new one,
  never half of one.
- An error is logged, never raised. A file that is missing or can't be read is the same as no file: the daemon
  starts without it.
- Each file is one topic. Deleting one resets only that topic, e.g. `people.json` for the order of the people.

## Why not SQLite

SQLite pays off for transactions across records, several processes that write, queries, or a lot of data. None of
these apply:

- No two files must change together.
- One process writes.
- The daemon reads each file once, at the start, and writes it whole.
- The data is small and grows slowly.

SQLite would cost a schema with versions and migrations, a migration from the JSON files, and more code and tests
for the same behaviour. People would also lose files they can read with `cat`, fix by hand or delete one at a time.

## When to look at it again

- A history: levels, events or presence over time.
- Many records, or a file that is written many times a second.
- A second process that writes, e.g. the GUI.
- Records that must change together.

## Not kept

What the daemon learns at runtime and keeps in memory only, by choice:

- The tokens Home Assistant refused (`homeassistant/client.py`), so that none is sent again to the same address. After
  a restart a refused token is tried once more. One failed login per start does not come near a ban, and a file
  would keep a secret, or its hash, on disk.
