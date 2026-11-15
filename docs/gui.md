# GUI

`xtouch-daemon gui` edits the configuration file in a window and applies it to the running daemon.

## Install and start

The GUI needs the `gui` extra (PyQt6). The wheels bring Qt along, so it needs no system packages:

```shell
uv tool install --force './xtouch-daemon[gui]'
xtouch-daemon gui            # the default configuration file
xtouch-daemon gui -c FILE    # another one
```

Without the extra, `xtouch-daemon gui` says how to install it.

## The window

- **The strips on top** show the device: the LCDs, LEDs, rings, faders and meters.
- **Below them, two tabs:** "Strip N" holds the options of the selected strip. "Global settings" holds `[behavior]`,
  `[aliases]`, `[mqtt]` (as "Home Assistant") and `[device]`. A global setting never looks like an option of the
  selected strip.
- **The footer** shows the file, whether the device runs it, the problems, and the buttons Undo, Redo, Revert and
  "Save and apply".
- **The header** shows the state of the service with a button to install, start or restart it, what the sound server
  has, the zoom, and a switch between the dark and the light theme.

## Zoom

Ctrl++ (or Ctrl+=) makes the whole window larger, Ctrl+- smaller, Ctrl+0 goes back to 100 %; the zoom button in the
header ("100 %") has the levels from 67 % to 300 %. The GUI keeps the zoom for the next start, like the theme.

Qt scales a window only when it opens, so a new zoom opens the window again at the new size: unsaved changes, undo,
the selected strip and the page stay. The zoom is on top of a `QT_SCALE_FACTOR` of the environment.

## Live view and preview

While the daemon runs, the strips show what the device shows right now ("Live"), read from the daemon's live view.
Without a running daemon they show what the configuration file would show ("File preview"), and the window says so.
A daemon that runs while the device is not connected shows "Live · X-Touch-Ext not connected": the strips show what
the device will show once it is there.

While the daemon runs with an `[mqtt]` section, a second pill tells how its connection to Home Assistant is doing:
"Home Assistant" while it is connected, otherwise what is wrong, e.g. "Home Assistant · not authorized" or
"Home Assistant · refused". Its tooltip has the broker's own words and what to check; a click opens the settings.

A strip with unsaved changes shows how it will look once saved, marked with a dot; the others stay live. Strips after
the configured ones are drawn fainter: they are not configured, so they are `auto` strips.

## Selecting and moving strips

| Action | Mouse | Keyboard |
|---|---|---|
| Select a strip | Click it. | Left/Right arrows, Home, End. |
| Move a strip | Drag it. The others make room where it goes. | Ctrl+Left, Ctrl+Right. |
| Cancel a drag | | Escape. |
| Remove a strip | Context menu, or "Remove" on its tab. | Delete. |
| Configure a strip that is not configured | Double-click it, or its context menu. | |

Only configured strips move, and only among each other. Removing a strip moves the strips right of it to the left; the
free places are `auto` strips. The tab of a strip also has buttons to move it left and right.

## Editing options

The forms come from the options of the configuration, so every option has a field:

- switches for on/off options, numbers with their ranges, choices, color swatches, lists as chips, masked fields for
  secrets, and file pickers;
- the help of each option under its name, and a button that sets it back to its default;
- the errors next to the options they belong to, with the same messages as `xtouch-daemon check-config`. The
  problems button in the footer lists them all; a click opens the page of the problem. An unknown option can be
  removed from there.

`[mqtt]` can be added and removed on its page. Above its options, the page shows how the daemon's connection is
doing (or that the daemon runs without the section, which it reads only when it starts), and "Test connection"
connects once with the settings as they are in the editor, saved or not, and says what is wrong if that fails.

## Suggestions from the sound server

The GUI reads the sound server and suggests what it has:

| Option | Suggestions |
|---|---|
| `device` | The outputs or inputs by node name, with their descriptions; the default is marked. |
| `profiles` | The profiles of the sound cards of those devices; the active one is marked. |
| `match`, `behavior.ignore` | The names and binaries of the applications that play. |
| `[aliases]` | The names of the applications that play. |

The refresh button in the header reads the sound server again, e.g. after you started an application. Without a
sound server, type the names by hand.

## Undo

Every edit can be undone: Ctrl+Z undoes, Ctrl+Shift+Z redoes. That includes removing a strip and reverting the file,
so neither asks first. Typing into one option is one step. Ctrl+Z undoes in the document also while a text field has
the focus.

Closing the window with unsaved changes asks whether to save them.

## Save and apply

"Save and apply" (Ctrl+S) writes the file and reloads the daemon:

- It saves only a file without problems: the daemon would not take one with problems.
- Unchanged values keep their place and their comments, and moved strips take theirs along. The file is written in
  place, so a symlinked configuration stays one.
- It reloads the running daemon when that reads the saved file: the service, or one started from a terminal or an
  IDE.
- A changed `[device] name` is reloaded, but takes a restart to take effect. A changed `[mqtt]` section is not
  reloaded at all. In both cases the window offers "Restart the service" for the service; restart a daemon that runs
  elsewhere where it runs.
- It then tells whether the device runs the saved file: "The device runs the saved file", or "The device does not run
  the saved file yet". If that stays, the daemon did not take the file, and its log says why
  (`journalctl --user -u xtouch-daemon`).

"Revert" drops the changes and reads the file again (Undo brings them back).

## The service

The service button installs, starts and restarts the systemd user service, the same as
`xtouch-daemon install-service`. It asks before it installs or starts it.

A daemon that runs outside systemd (e.g. from a terminal or an IDE) is found too: the header shows "running
elsewhere", and saving reloads it. The GUI does not start or restart that one: restart it where it runs.
