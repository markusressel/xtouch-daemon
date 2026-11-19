# Design: launching applications

Status: built. How to use it: [Applications](../../configuration/channels/applications.md#launching-the-application)
and [People](../../configuration/channels/people.md).

The idea: the Select button of a strip whose application is not there starts it. A "VoIP" strip starts Mumble and
connects it to the server, a "Music" strip starts the music player.

## Where it goes

| Where | `launch` |
|---|---|
| An `apps` channel | Select launches while none of its applications runs. |
| `[controls]` of a slot: `select = { launch = [...] }` | Select of that slot launches, whatever the slot shows, while its `when` holds. This is how the voice chat starts: `7 = { select = { launch = ["mumble", "mumble://..."] }, when = "not call" }` on the slot VoIP shows on in a call. |
| `output`, `input` channels | Not allowed: Select makes the device the default. |
| `homeassistant` channels | Not allowed: Home Assistant owns the strip and must never send a command. |
| `person` channels, `[pool.people]`, places | Not allowed: a launch is a control of the slot. |

- `launch`: the program, then its arguments, as a list; not empty, and no part empty.
- A single string is accepted too and split with `shlex.split` (quotes like a shell, nothing expanded: no `~`, `$VAR`,
  globs, pipes or `&&`). A command line is what people copy from a `.desktop` file or a terminal; the GUI's chips
  stay the canonical form (it saves a list). The split happens at validation, so `check-config` and the GUI show the
  parts.
- `launch_when_running`: Select starts the command also while the application runs. For Mumble that is useful: a
  running Mumble takes the URL and connects, and `mumble` without a URL brings its window to the front.

## Mumble URLs

From the [Mumble documentation](https://www.mumble.info/documentation/user/mumble-url/):

```
mumble://[username[:password]@]<address>[:port]/[channelpath][?title=<servername>][&url=<serverurl>]
```

- The port defaults to 64738. Special characters of the channel path must be URL-encoded (`Gaming%20Night`).
  Subchannels are separated by `/`. When the channel can't be reached, Mumble stays in the default channel.
- `?version=1.2.0` was needed only before Mumble 1.2.4. `title` and `url` matter only when the link is dropped
  into the server browser.
- A password in the URL ends up in the configuration file and in the process list (`/proc/*/cmdline` is readable by
  every user). Leave it out and let Mumble remember it, or use a certificate.

A running Mumble accepts the URL too: on Linux, Mumble's `main.cpp` hands the URL of a second instance over D-Bus
(`openUrl` on `info.mumble.mumble`, then the legacy `net.sourceforge.mumble.mumble`) to the running one and exits;
without a URL it asks the running one to `focus`. Only `--multiple` starts a second client. Verified in the source
(`src/mumble/main.cpp`), not with a real Mumble.

## When an application "runs"

Select launches only while the application doesn't run:

- **An `apps` channel** runs while a stream matches `match`, a process whose name contains one of the `match` entries
  runs, or the program of `launch` runs. So a silent Mumble (no stream) counts.
- **A control** runs while the program of its `launch` runs.

- Processes are matched like the `processes` of states (`system/processes.py`): the kernel's `comm` and the file name
  of the program, in lower case, containing the pattern. They are read every 2 s (`binder.PROCESS_INTERVAL`) while
  anything needs them.
- The program of `launch` is the file name of its first part, matched exactly: `flatpak` must not match
  `flatpak-portal`, which runs all the time. For `["flatpak", "run", "info.mumble.Mumble"]` that is useless (the
  program is `flatpak`), so name the application in `match`.
- A `match` entry like `signal` also counts unrelated processes whose name contains it. The cost is a Select that does
  nothing; `list-apps` and `ps -e` show what runs.

## Starting it

- **Never through a shell.** The list goes to `exec` as it is.
- **Detached from the daemon's service.** With a systemd user manager (its socket
  `$XDG_RUNTIME_DIR/systemd/private`) and `systemd-run` in `PATH`:
  `systemd-run --user --quiet --collect --unit=xtouch-launch-<program>-<random> --property=WorkingDirectory=~ -- argv…`.
  Otherwise a plain process in a session of its own (`start_new_session`), stdin/stdout/stderr on `/dev/null`, waited
  for by a thread so it does not stay a zombie.
- **Deviation from the first idea, `systemd-run --scope`:** a scope runs the command as a child of `systemd-run`,
  which is a child of the daemon, with the daemon's environment. The daemon's service starts with
  `default.target`, often before the desktop imports `WAYLAND_DISPLAY`/`DISPLAY` into the user manager, so a GUI
  application started from a scope may find no display. A transient *service* gets the user manager's environment
  of the moment, is not a child of the daemon (no zombie, survives a restart of the daemon without question), and
  its output goes to the journal (`journalctl --user -u 'xtouch-launch-*'`). `--collect` removes the unit also when
  it failed.
- **Logging:** every start is logged (info, with the command), a program that is not in `PATH` is a warning (checked
  before, with `shutil.which`, so `systemd-run` does not fail later in the background), an `OSError` of the start a
  warning, an exit of the started process with an error code (fallback mode, or `systemd-run` itself) a warning. A
  launch that does not show up in 15 s is a warning. Nothing of it stops the daemon.
- **Debounce:** no second launch within 5 s (`LAUNCH_DEBOUNCE`) of the last one while the application is not up yet,
  so a double press starts it once.
- **Reload:** the launch state belongs to the strip or control and starts anew with a reload; the started
  application is not affected.

## The Select LED

It flashes while launching (until the application runs, at most 15 s, `LAUNCH_TIMEOUT`), is on while it runs, and off
otherwise; without `launch` it stays off. The device flashes the LED itself (Mackie Control `Led.FLASH`); the daemon
sends it once.

## Security

- Commands come only from the configuration: the file, or the configuration of a live preview. The live view only
  accepts clients of the same user (`SO_PEERCRED` in `live.py`), who could edit the file anyway. A preview whose
  `launch` runs something is no more than that user can do in a shell.
- Home Assistant and MQTT can never send a command: nothing arriving over MQTT reaches `launch`, and `homeassistant`
  channels can't have it.
- **No Home Assistant button entity for now.** A `button` per launch that runs the configured command would be safe
  (it runs only the configured command, never one from MQTT), but it lets anyone who can press buttons in Home
  Assistant start programs on the desktop, also while nobody sits there. Left out until there is a use for it.

## Later

- **Focus the window** when Select is pressed while the application runs. On Wayland there is no portable way
  (KWin scripts, GNOME extensions, the Sway/Hyprland IPC differ, see [Layouts](../history/layouts.md#what-others-do)). For Mumble,
  `launch_when_running` with `launch = ["mumble"]` already does it through Mumble's own D-Bus `focus`.
- A `launch_process` option for commands whose program is not the application (`flatpak run`, `gtk-launch`), if
  `match` turns out not to be enough.
- A Home Assistant `button` (see Security).
