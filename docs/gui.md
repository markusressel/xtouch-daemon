# GUI

`xtouch-daemon gui` edits the configuration file in a window and applies it to the running daemon.

## Install and start

On Arch Linux, install the package `xtouch-daemon-gui-bin` (see [Getting started](getting-started.md#arch-linux)).
It uses the system's PyQt6, and starts with `xtouch-daemon-gui` or "X-Touch Extender" in the menu of the desktop:

```shell
xtouch-daemon-gui            # the default configuration file
xtouch-daemon-gui -c FILE    # another one
```

From a checkout, the GUI needs the `gui` extra (PyQt6). The wheels bring Qt along, so it needs no system packages:

```shell
uv tool install --force './xtouch-daemon[gui]'
xtouch-daemon gui            # the default configuration file
xtouch-daemon gui -c FILE    # another one
```

Without the extra, `xtouch-daemon gui` says how to install it.

## The window

- **The strips on top** show the device, laid out and labeled like it: the encoder with its ring of 13 LEDs (Mackie
  Control lights the middle 11), the LCD, the meter next to Rec, Solo, Mute and Select, and the fader with its dB
  scale: the middle of the cap marks the value, -∞ at the bottom, 0 dB at 77 % of the travel (`behavior.unity_at`).
  The type of each strip is printed under its LCD.
- **A handle under the strips** (the short bar) makes them larger or smaller: drag it down for larger strips, up
  for more room below. The strips keep their proportions, and the GUI keeps the size for the next start.
- **Below them, two tabs:** "Strip N" holds the options of the selected strip. "Global settings" holds `[behavior]`,
  `[aliases]`, `[mqtt]` (as "Home Assistant") and `[device]`. A global setting never looks like an option of the
  selected strip.
- **The footer** shows the file, whether the device runs it, the problems, and the buttons Undo, Redo, Revert and
  "Save and apply".
- **The header** shows the state of the service with buttons to install, start, restart or stop it, which unit it
  runs (see [The service](#the-service)), what the sound server has, the zoom, and a switch between the dark and the
  light theme.

## The service

Next to the state of the service, the header shows which unit systemd uses: "packaged" for the one of the Arch Linux
package (`/usr/lib/systemd/user/xtouch-daemon.service`), or "from" and the program of a unit in
`~/.config/systemd/user`, which [`install-service`](commands.md#install-service) wrote, e.g. for a checkout.

- **Install and start** takes the unit of the package when the GUI is the one of the package: it enables and starts
  it, and writes no file. Any other GUI writes a unit for its own `xtouch-daemon` to `~/.config/systemd/user`.
- **Use the packaged unit** shows while a unit in `~/.config/systemd/user` overrides the one of the package. It removes
  that file; an enabled service stays enabled, and a running one restarts with the program of the package.
- **Restart** stands out (with a tooltip that names both versions) when the daemon runs another version than the one
  installed, e.g. after an upgrade of the package: the daemon keeps running the old version until it restarts. This
  needs a daemon that tells its version (0.1.0 and later), and only counts for the service of the installation the
  GUI runs from.

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
- the help of each option under its field, with its default and, where the documentation explains more, a
  "Learn more" link to that section; a button sets the option back to its default;
- for choices, what the chosen value does (e.g. `recording` for the Rec LED), and each value says it as a tooltip in
  the list; the type of a strip says what that type controls;
- the errors next to the options they belong to, with the same messages as `xtouch-daemon check-config`. The
  problems button in the footer lists them all; a click opens the page of the problem. An unknown option can be
  removed from there.

`[mqtt]` can be added and removed on its page. Above its options, the page shows how the daemon's connection is
doing (or that the daemon runs without the section, which it reads only when it starts), and "Test connection"
connects once with the settings as they are in the editor, saved or not, and says what is wrong if that fails.

## Changing the type of a strip

The buttons above the options of a strip change its type. Options the new type has too stay as they are, e.g. `label`
and `color`. The others are not lost: the editor keeps them in the strip's table in the file, as a comment the daemon
ignores, and switching back to the type restores them. That also works after saving and closing the GUI:

```toml
[[strip]]
type = "empty"
# kept from type = "output" (the GUI restores these when the strip is switched back):
# device = "bluez_output.*"
# profiles = [
#   { label = "Phones", profile = "output:analog-stereo+input:analog-stereo" },
#   { label = "Speaker", profile = "output:iec958-stereo+input:analog-stereo" },
# ]
```

The page of the strip names the options it keeps, and for which type. Restored options look as they did in the file,
comments included. A comment edited by hand into something that is no TOML any more stays in the file as it is; the
page says so. Ctrl+Z undoes a change of the type with what it kept and restored.

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
`xtouch-daemon install-service`. It asks before it installs or starts it. While the service runs, "Stop" next to it
stops it (`systemctl --user stop`): it stays enabled, so it starts again with the next session, or with "Start".

A daemon that runs outside systemd (e.g. from a terminal or an IDE) is found too: the header shows "running
elsewhere", and saving reloads it. The GUI does not start, restart or stop that one: restart it where it runs.
