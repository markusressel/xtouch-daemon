# Design: several users on one machine

Status: thought about, not built. There was no need: the machines of the maintainer have one user each.

## Problem

Each user who is logged in has their own `systemd --user`, so each one can have their own `xtouch-daemon` service,
with their own configuration and their own PipeWire. There is one device. Which user's audio does it control?

## What happens today

- **Access.** `/dev/snd/midiC*D0` belongs to `root:audio`, mode `rw-rw----`. logind (`uaccess`) adds an ACL for the
  user of the active session on the seat. A user whose session is in the background has no access, unless they are
  in the group `audio`.
- **One daemon gets the device.** `hardware/midi.py` opens the raw MIDI device with `os.open(path, O_RDWR |
  O_NONBLOCK)`, and a raw MIDI device opens once. The first daemon keeps it. A second one gets `EBUSY`, logs `Can't
  open <device>: <error>` (`Surface.connect()` in `hardware/surface.py`) and tries again at every reconnect.
- **A user switch changes nothing.** logind moves the ACL to the new active user. As far as we know, it does not
  revoke a file descriptor that is already open. So the device goes on controlling the audio of the first user,
  while the second one sees their daemon wait for it.

## What it would take

- Watch logind on the system bus: the property `Active` of the daemon's own session.
- When the session goes to the background, close the device, so the daemon of the active user can open it.
- When the session comes back, connect again, as after a reconnect.

One daemon for all users is not an option: the daemon refuses to run as root (see
[Troubleshooting](../../guides/troubleshooting.md#starting)). Each user runs their own.
