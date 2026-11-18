# GUI

`xtouch-daemon gui` edits the configuration file in a window and applies it to the running daemon.

It edits [channels, states and slots](configuration/slots.md).

![The GUI: the window Device at the top, the slots and the inspector of slot 3 below](images/gui.png)

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

The rail on the left has four pages:

- **Slots:** what each slot shows when, see [The slots](#the-slots).
- **Channels:** the channels of the file, then the built-in pools `[pool.apps]`, `[pool.people]`, `[pool.auto]` and `[pool.devices]`.
  Add (by type), Duplicate and Remove; the id can be renamed. Each says where it is used (`slot 2`, `pool games`, `state call`).
- **States:** the modes first, then the other states. The form asks in order: State or Mode (a mode has a label and
  a priority), and On while: Sources or Condition, never both. Sources lists only the ones the state has, each with
  ✕ to remove it; Add source offers the others ("An application plays", "You are in the voice chat", ...), and the
  state is on while any of them is. Condition takes a [condition](configuration/slots.md#conditions) of other states
  and modes, in the field of the page Slots. Switching between them asks before it removes what the other had.
  Delays and overrides (`delay_on`, `delay_off`, `persist`) are folded away until a state has one. Above the form:
  what the daemon says about it right now (since when, from which source), its override (a mode: picked by hand),
  and which stacks and controls use it.
- **Settings:** `[behavior]`, `[aliases]`, `[mqtt]` (as "Home Assistant"), `[switching]` (as "Modes and chord"),
  `[voip]` (as "Voice chat") and `[device]`. "Voice chat" also tells whether Mumble is connected, lists the steps of
  its setup, and installs the [Mumble plugin](integrations/mumble.md) with "Install Mumble plugin".

Slots, Channels and States have a list or the slots on the left and what is picked on the right. The handle between
them (the short upright bar) gives either side more room; each page keeps its share for the next start.

The window **Device** shows the device on every page, above the page at first. Its title bar moves it to another side
of the window, or out of it as a window of its own (e.g. on another screen); View → Device closes and opens it. The
GUI keeps where it is for the next start. Clicking a strip of it (or Left, Right, Home, End) shows its slot on the
page Slots.

The drawing of the device shows the encoder with its ring of 13 LEDs (Mackie Control lights the middle 11), the LCD
(the backlight in the strip's color shines around a dark panel and through its characters, as on the device), the
meter next to Rec, Solo, Mute and Select, and the fader with its dB scale: the middle of the cap marks the value, -∞
at the bottom, 0 dB at 77 % of the travel (`behavior.unity_at`). What each slot shows is printed under its LCD.

The footer shows the problems, whether the device runs the file, the switch [Try on the device](#try-on-the-device)
while there are unsaved changes, and the buttons Undo, Redo, Revert and "Save and apply". The header has the state of
the service with buttons to
install, start, restart or stop it (see [The service](#the-service)), and what the sound server has.

States, channels and slots have a color each, in the whole window: states (and modes) violet, channels (and what
else a slot can show: pools, people) teal, slots orange. The icons of their pages on the rail, the chips of the
slots, the state bar and the words and sections in the help (`[state.gaming]`, "the slot") have them.

The menus have what is used now and then: File (Save and apply, Revert, Quit), Edit (Undo, Redo), View (the window
Device, the dark or the light theme, the [zoom](#zoom)) and Help (this documentation).

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

Ctrl++ (or Ctrl+=) makes the whole window larger, Ctrl+- smaller, Ctrl+0 goes back to 100 %; View → Zoom has the
levels from 67 % to 300 %. The GUI keeps the zoom for the next start, like the theme.

Qt scales a window only when it opens, so a new zoom opens the window again at the new size: unsaved changes, undo,
the selected slot and the page stay. The zoom is on top of a `QT_SCALE_FACTOR` of the environment.

## Live view

While the daemon runs, the drawing shows what the device shows right now ("Live"), read from the daemon's live
view. Without a running daemon it is dark, and the window says so. A daemon that runs while the device is not
connected shows "Live · X-Touch-Ext not connected": the strips show what the device will show once it is there.

While the daemon runs with an `[mqtt]` section, a second pill tells how its connection to Home Assistant is doing:
"Home Assistant" while it is connected, otherwise what is wrong, e.g. "Home Assistant · not authorized" or
"Home Assistant · refused". Its tooltip has the broker's own words and what to check; a click opens the settings.

With the [virtual device](getting-started.md#without-a-device) (`run --virtual-device`), the pill says "Live · virtual
device" once the daemon drives it, and "virtual device not running · Open it" while the daemon waits for it: a click
opens it in the window (see [below](#the-virtual-device)).

A third pill shows the mode ("Mode gaming", "Mode gaming · by hand"); its tooltip lists the states and what each slot
shows.

## Select and Play

A bar above the drawing of the device switches what the mouse does on it:

- **Select:** a click picks a strip, and with it its slot on the page Slots. Dragging a strip moves its slot to
  another place: the strip lifts out of the row, the others glide aside, and a dashed place shows where it goes;
  Escape puts it back. Ctrl+Left/Right and the context menu (Move left, Move right) do the same. A slot takes its
  candidates (`[slots]`) and its controls (`[controls]`) along, the slots in between make room; Ctrl+Z moves it back.
  Comments above the slots in the file stay where they are.
- **Play:** the mouse is a hand on the device:
  - a fader: press to touch it, drag to move it, release to let go; Alt-drag moves it without a touch, like the
    device moving it by itself (the daemon puts it back);
  - a button: held while the mouse button is down;
  - an encoder: the wheel turns it, a click pushes it.

Play works on the virtual device the window hosts, and on the device of a running daemon: then the daemon takes what
the mouse does as if the device sent it, so the mixer acts and a motorized fader follows once it is let go. The fader
under the mouse is drawn there at once. Play is off while Simulate shows only the drawing (it works when Simulate runs on
the device, see [Try on the device](#try-on-the-device)), without a daemon (or with one of another user, or too old to
take it) and while the device is not connected; its tooltip says why.

While no daemon runs, "Try without a device" starts one with the virtual device on this file (saved first if it is
new) and opens the device in the window, in Play: to set everything up and try it before there is a device. That
daemon ends with the window.

## The virtual device

While the window hosts the virtual device, Play is on (see [Select and Play](#select-and-play)).

A bar above the drawing unplugs it and plugs it in again, switches it off and on (the faders go down by themselves,
as on the device), and breaks the touch sensor of faders ("Broken touch"), to try `touchless_faders`. "Close" closes
it, and so does closing the window: for the daemon it is unplugged. What the drawing shows still comes from the
daemon, which is what reached the device.

## Try on the device

Next to Save and apply, a pill says what the device runs: "Saved, on the device", "Unsaved changes" (the device
runs the saved file), "On the device, not saved", or what is wrong (e.g. "Not running", "Not on the device yet"), with
the details in its tooltip.

While there are unsaved changes, the switch "Try on the device" sits next to it: the device runs the configuration in
the editor before it is saved, and follows every change a moment after it (undo and redo too). The file is not
written. Without unsaved changes the switch is gone: the device runs the file anyway. Once on, it stays on for the
next changes until it is turned off or the window closes; a new window starts with it off.

- **While it is on**, the pill says "On the device, not saved" ("Sending to the device…" for a moment after a change).
- **Save and apply** makes it the configuration: the daemon loads the saved file, which is what the device shows
  already.
- **Back to the file:** turning the switch off, closing the window (it asks about unsaved changes as usual, and says
  that the device runs them) or "Revert" brings back the saved file. So does a window that crashed: the daemon goes
  back to the file when the connection of the window ends, or when the window does not answer for 10 seconds. The
  file also comes back when it changes on disk, or the daemon is reloaded; then the switch goes off and the window
  says why.
- **What the daemon does not take** shows in red under the status bar at the top, and the device keeps the version
  before. It can't change `[mqtt]` (that takes a save and a restart), and a changed `[device] name` takes effect only
  with a restart. A configuration with problems is not sent at all: the pill says "Paused: problems" until they are
  fixed.
- **Channels, states and slots** are all part of it: a stack changed in the editor shows on the device as it is.
- **Simulate on the device:** while Simulate is open on the page Slots, the switch is there too (also without unsaved
  changes), and turned on, the device shows the what-if of Simulate instead of what really happens, with the changes
  if there are any: the states and the mode it sets, its channels present or absent, and its people, applications and
  devices (real ones first, so their faders move real audio; made-up ones for the rest, `App 1`, `Device 1`). Delays
  and dwells apply as they really do. The drawing shows the device then, the cards the daemon's slots and why, Play
  works, and the pill says "On the device · simulated". Ending Simulate (Esc) shows what really happens again. Home
  Assistant never sees it: its slot and state sensors stay as they really are, and nothing of it is kept. With the
  switch off, Simulate only draws; its bar says "Only in the drawing".
- **One window at a time:** a second window that turns it on takes over, and the first one's switch goes off.
- **Home Assistant:** channels the changes do not have keep their entities in Home Assistant (with their state; only
  nothing drives them), so they are as before once the file runs again. Entities of channels only the changes had are
  removed again when it ends.

The switch is disabled, and its tooltip says why, while no daemon runs, while the daemon reads another file, and for a
daemon from before this feature (restart it to run the installed version).

## The slots

On the page Slots:

- **The state bar** lists the states and modes: ● on, ○ off, with the override in brackets. Its menu overrides a
  state (`auto`, `on`, `off`) or picks a mode (`pick`, `auto`), like Home Assistant or `xtouch-daemon mode`.
- **A card per slot** lists its candidates as rules, read from the top like "if, else if, else": the first whose
  condition holds wins. `when gaming → auto` shows `auto` while `gaming` is on, `otherwise → browser` below it `browser`
  the rest of the time (`always` for a lone candidate without a condition). A pool without a condition reads `when app
  without a slot → apps` (an outlined chip): it shows only while it has a member no other slot has, else the slot goes
  on to the next candidate. A tiny LCD after what it shows has the color of the strip: the candidate's own `color`, else
  the channel's or the pool's, else white (two for `auto`: applications and people; one per color for a pool of
  channels; dark for `-`). Its tooltip says where the color comes from. A rail on the left joins the candidates from the
  top, with "else" between two and a node on each: green on the one the device shows (or Simulate would). Above it, the
  candidates are dimmed with why they did not win (`✗ browser doesn't play`, `✗ browser is on slot 3`); below it, dimmed
  more: not reached. When none of them has anything to show (e.g. the last is a pool with no member left), all are
  dimmed with why (`✗ no person without a slot`) and the rail ends in a row of its own, "nothing to show: the strip is
  dark", which is the one shown. On the one shown, the chip of a pool names what it hands out there (`apps · firefox`,
  `people · Alice`), and its tooltip who else waits for a slot. A card that gets a line more or less grows or shrinks
  smoothly. Conditions are outlined chips, what the slot shows a filled one. The states are violet (`call`, `not
  gaming`, one per `or`). `present` is spelled out in an olive chip (green in the light theme), in what it means for the
  type of the channel or pool: `browser if present` reads `when browser plays → browser`, `mic if present` `mic is
  connected`, `mum if present` `mum is in the voice chat`, `present(people)` `someone is in the voice chat`. What the
  slot shows is teal (see [the colors](#the-window)), and the green node is on the row that shows (on `people` while a
  person sits there, also when `apps` is above it). Options of the strip in that slot only follow as in the file (`color
  = white, rec = recording`). + adds `auto` at the end, the bin removes the candidate picked. Drag a candidate, or move
  it with Ctrl+Up and Ctrl+Down. A slot without candidates shows `auto`.
- **The inspector** edits the candidate picked: what it shows (a channel, a pool such as `apps`, `people` or
  `auto`, `-`), when (the
  [condition](configuration/slots.md#conditions):
  states violet, channels in `present(...)` teal, a mistake underlined in red with what is wrong in its tooltip;
  typing offers the states, keywords and channels that fit, Ctrl+Space all of them),
  and the options of its place (look, on `apps` and `auto` the encoder and the volume range, on `people` the look of
  a person's strip). It says why the slot shows what it shows (the same as `xtouch-daemon why 2`), which channel the
  candidate shows, where else that is used and where it is now, or what a pool hands out and from which side, with "Edit the channel" to its page; below, the controls of the slot (`[controls]`).

Clicking a strip in the window Device (or Left, Right, Home, End) picks its card, with the candidate it shows.

**Simulate** shows what the slots would show in another mode, with other states on, with channels absent (`auto
plays`: an application plays; `people fill`, `apps fill`: as many as there are slots), or with so many people in the
call and applications that play (the two counts; the strips show their names): a frame goes around the drawing in the window Device, a bar of what-ifs replaces the state bar,
and the drawing, the cards and the why line follow it. With "Try on the device" on, the device shows it too (see
[Try on the device](#try-on-the-device)); else nothing is sent to the daemon. Esc, or Simulate again, ends it.

## Editing options

The forms come from the options of the configuration, so every option has a field. The options of a channel are in
cards in the order of the device, from top to bottom: what it controls, the encoder, the display, the buttons (Rec,
Solo, Mute, Select), the fader and the meter, then those about slots (`tags`, `in_pool`, ...).

The cards of the encoder, the display, the buttons and the fader have a drawing of that part of the strip, which shows
what the options do on the device in a few steps (‹ and › go through them), each with a caption: the ring as the encoder turns and is pushed, the LCD while audio
plays, while muted and with nothing to control, which LEDs light while audio plays, an application records or the
strip is muted, and the volume at the bottom, at the 0 dB mark and at the top of the fader, with what the meter shows
there. It follows the values in the form at once, saved or not, at the step shown.

- switches for on/off options, numbers with their ranges, choices, color swatches, lists as chips, masked fields for
  secrets, and file pickers;
- the help of each option under its field, with its default and, where the documentation explains more, a
  "Learn more" link to that section; a button sets the option back to its default;
- `choices` as a table, with the devices, the sound cards and the profiles of the card of each line to pick from.
  While a channel has `choices`, `device` and `profiles` are hidden, and the other way around: a channel has one or
  the other;
- for choices, what the chosen value does (e.g. `recording` for the Rec LED), and each value says it as a tooltip in
  the list;
- the mouse wheel scrolls the page, also over a number or a choice: it never changes a value;
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
| `match`, `exclude` of `[pool.apps]`, `apps` and `recording` of a state | The [presets](configuration/presets.md) (`@browsers`, ...) first, then the names and binaries of the applications that play. A preset's tooltip tells what it stands for; its chip is outlined. |
| `processes` of a state | The presets for processes. |
| `[aliases]` | The names of the applications that play. |
| `person` of a `person` channel | The people in the voice chat now, as the running daemon tells them. |

The refresh button in the header reads the sound server again, e.g. after you started an application. Without a
sound server, type the names by hand. The people of the voice chat come from the daemon's live view: without a
running daemon (or nobody in the channel), type the names by hand.

## Undo

Every edit can be undone: Ctrl+Z undoes, Ctrl+Shift+Z redoes. That includes removing a channel and reverting the file,
so neither asks first. Typing into one option is one step. Ctrl+Z undoes in the document also while a text field has
the focus.

Closing the window with unsaved changes asks whether to save them.

## Save and apply

"Save and apply" (Ctrl+S) writes the file and reloads the daemon:

- It saves only a file without problems: the daemon would not take one with problems.
- Unchanged values keep their place and their comments, and a stack keeps its form (a string, a list, tables) where
  it did not change. The file is written in place, so a symlinked configuration stays one.
- It reloads the running daemon when that reads the saved file: the service, or one started from a terminal or an
  IDE.
- Without changes it is there too while the daemon runs another version of the file, e.g. one edited outside the
  GUI: then it only reloads the daemon.
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
