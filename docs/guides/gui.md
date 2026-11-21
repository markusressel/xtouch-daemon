# GUI

`xtouch-daemon gui` edits the configuration file in a window and applies it to the running daemon. It starts with
`xtouch-daemon-gui` (the Arch Linux package) or `xtouch-daemon gui`, `-c FILE` for another file; see
[Install](../getting-started/install.md#the-gui).

It edits [channels, states and slots](../configuration/slots.md). New here? The [Setup tour](../getting-started/tour.md)
builds a configuration with it, page by page; this page is the reference.

![The GUI: the window Device at the top, the slots and the inspector of slot 3 below](../images/gui.png)

## The window

The window **Configuration** has a rail of four pages on its left, icons only (» at its foot shows their names, « hides
them again; the GUI remembers it):

- **Slots:** what each slot shows when, see [The slots](#the-slots).
- **Channels:** two groups: the channels (each takes one strip), then the pools (each supplies a member to every slot that names it): the built-in `[pool.apps]`, `[pool.people]`, `[pool.auto]` and `[pool.devices]`. The box Shows of a candidate on the page Slots has the same two groups.
  Add (by type, or a pool of channels of your own), Duplicate and Remove; the id of a channel or pool can be renamed (the slots, conditions, pools and controls that name it follow). Each says where it is used (`slot 2`, `pool games`, `state call`).
- **States:** the modes first, then the other states. The form asks in order: State or Mode (a mode has a label and
  a priority), and On while: Sources or Condition, never both. Sources lists only the ones the state has, each with
  ✕ to remove it; Add source offers the others ("An application plays", "You are in the voice chat", ...), and the
  state is on while any of them is. Condition takes a [condition](../configuration/slots.md#conditions) of other states
  and modes, in the field of the page Slots. Switching between them asks before it removes what the other had.
  Delays and overrides (`delay_on`, `delay_off`, `persist`) are folded away until a state has one. Above the form:
  what the daemon says about it right now (since when, from which source), its override (a mode: picked by hand),
  and which stacks and controls use it.
- **Settings:** `[behavior]`, `[aliases]`, `[mqtt]` (as "[Home Assistant](home-assistant.md)"), `[homeassistant]` (as
  "[Home Assistant API](home-assistant.md#homeassistant)"), `[switching]` (as "Modes and chord"),
  `[voip]` (as "Voice chat") and `[device]` (as "Extender": the sound card of the extender, touch sensors, start-up). "Voice chat" also tells whether Mumble is connected, lists the steps of
  its setup, and installs the [Mumble plugin](mumble.md) with "Install Mumble plugin".

Slots, Channels and States have a list or the slots on the left and what is picked on the right. The handle between
them (the short upright bar) gives either side more room; each page keeps its share for the next start.

The window **Device** shows the device on every page, above the window Configuration at first. The title bar of either
moves it to another side of the window, next to the other one, or out of it as a window of its own (e.g. on another
screen); View → Device closes and opens the device (Configuration always stays open). The GUI keeps where they are for
the next start. Clicking a strip of it (or Left, Right, Home, End) shows its slot on the
page Slots.

The drawing of the device shows the [encoder](../configuration/strip/encoders.md) with its ring of 13 [LEDs](../configuration/strip/leds.md) (Mackie Control lights the middle 11), the LCD
(the backlight in the strip's color shines around a dark panel and through its characters, as on the device), the
meter next to Rec, Solo, Mute and Select, and the fader with its dB scale: the middle of the cap marks the value, -∞
at the bottom, 0 dB at 77 % of the travel (`behavior.unity_at`). What each slot shows is printed under its LCD.

The footer shows the problems, whether the device runs the file, the control [Preview](#preview)
while there are unsaved changes or Simulate is open, and the buttons Undo, Redo, Revert and "Save and apply". The title of the window
names the file, with • while there are unsaved changes. The header has the state of the service with buttons to
install, start, restart or stop it (see [The service](#the-service)), and what the sound server has.

**Help where you look:** while the mouse is on something with a tooltip, the footer shows its first sentence at once,
in place of the status line; the tooltip itself follows after a moment, with the states, channels and slots it
names in their colors. A pill with ▾ opens what it means in full on
a click, with what can be done about it: a row per thing, with a bar in the color of how it does (a problem is
also tinted and its fix is the main button). A control that is off says why next to it (e.g. "Play: device not
connected").

States, channels and slots have a color each, in the whole window: states (and modes) violet, channels (and what
else a slot can show: pools, people) teal, slots orange. The icons of their pages on the rail, the chips of the
slots, the state bar and the words and sections in the help (`[state.gaming]`, "the slot", "an application",
`apps`) have them; a condition of presence (`present`) is yellow. The controls of the device (Select, Mute, the
fader, the encoder, ...) stand out from the help in the color of the text.

Lists and pages that scroll cast a soft shadow at an edge where more of them is hidden, and popovers a shadow on the
window under them.

The menus have what is used now and then: File (Save and apply, Revert, Quit), Edit (Undo, Redo), View (the window
Device, the window [Log](#log), the dark or the light theme, the [zoom](#zoom)) and Help (this documentation).
They open inside the window, as the lists of drop-down fields and of suggestions do: a screenshot key and the keys of
the window manager work while one is open. Alt and the underlined letter open a menu; the arrows, Enter and Esc work
in it as usual. The menus Add of the pages Channels and States say under each entry what it does.

## The service

The pill of the service in the header tells its state ("running", "stopped", "not installed", and the worst problem
of a connection of the daemon). A click on it opens what goes with it: the service with Install and start, Start or
Restart (the same as `xtouch-daemon install-service`) and, while it runs, Stop (`systemctl --user stop`: it stays
enabled, so it starts again with the next session, or with "Start"); the unit systemd uses; and the connections of the
daemon, each with its settings. Installing and starting ask first. What the service needs (Install and start, Start,
or Restart after an upgrade) also has its button next to the pill.

A daemon that runs outside systemd (e.g. from a terminal or an IDE) is found too: the header shows "running
elsewhere", and saving reloads it. The GUI does not start, restart or stop that one: restart it where it runs.

The unit is "packaged" for the one of the Arch Linux package (`/usr/lib/systemd/user/xtouch-daemon.service`), or
"own unit" for a unit in `~/.config/systemd/user`, which [`install-service`](../reference/commands.md#install-service)
wrote, e.g. for a checkout; the popover has its path and the program it starts.

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

While the daemon runs, the drawing shows what the device shows right now ("Live", in a pill on the right of the bar of
the window Device), read from the daemon's live view. Without a running daemon the strips are dark and the pill says "No daemon": the drawing is the device, and only the daemon drives it. Start it (`xtouch-daemon install-service --now`), or use "Try without a device", which starts a daemon with the virtual device. A
daemon that runs while the device is not connected shows "Live · not connected", with dark strips: the drawing is the
device, and there is none. They light up with the startup sequence once it is there. When the daemon stops, the
drawing shows its shutdown sequence too, until the strips are dark.

With the [virtual device](../getting-started/without-a-device.md) (`run --virtual-device`), the pill says "Live · virtual
device" once the daemon drives it, and "virtual device not running · Open it" while the daemon waits for it: a click
opens it in the window (see [below](#the-virtual-device)).

Next to it, a pill shows the [mode](../configuration/slots.md#states-and-modes) the device shows ("Mode: gaming", "No mode" while no mode is on, "· by hand" when
it was picked by hand). A mode is a state with `mode = true`: one at a time is on. A click lists the states, with what
turned each on, and picks a mode by hand ("Pick gaming", "Pick no mode", "Back to the rules").

The pill of the service at the top tells what the daemon is connected to: "running" while all is well, else the worst
problem, e.g. "running · Home Assistant not authorized" or "running · device not connected". A click lists each
connection (the device, the sound server, Home Assistant with an `[mqtt]` section, the Home Assistant API while a part
shows or sets an entity, the voice chat with `[voip]`), how it is doing and why (for Home Assistant the broker's own
words and what to check, for its API e.g. "bad token" or "unreachable"), with a button to its settings.

## Select and Play

A bar above the drawing of the device switches what the mouse does on it:

- **Select:** a click picks a strip, and with it its [slot](../configuration/slots.md) on the page Slots. Dragging a strip moves its slot to
  another place: the strip lifts out of the row, the others glide aside, and a dashed place shows where it goes;
  Escape puts it back. Ctrl+Left/Right and the context menu (Move left, Move right) do the same. A slot takes its
  candidates (`[slots]`) and its controls (`[controls]`) along, the slots in between make room; Ctrl+Z moves it back.
  Comments above the slots in the file stay where they are.
- **Play:** the mouse is a hand on the device, and the drawing looks like the device: no strip is selected, and
  there are no outlines of the selection, the focus or the mouse (the selection comes back with Select):
  - a fader: press to touch it, drag to move it, release to let go; Alt-drag moves it without a touch, like the
    device moving it by itself (the daemon puts it back);
  - a button: held while the mouse button is down;
  - an encoder: the wheel turns it (a touchpad too), and so does a drag on the knob (up or right turns it
    clockwise); a click pushes it, and holding the knob still holds it down; holding on an LED of the ring turns it
    until the ring lights that LED.

Play works on the [virtual device](#the-virtual-device) the window hosts, and on the device of a running daemon: then the daemon takes what
the mouse does as if the device sent it, so the mixer acts and a motorized fader follows once it is let go. The fader
under the mouse is drawn there at once. While the drawing shows the preview in the GUI, Play acts on the virtual twin
in the daemon (see [Preview](#preview)). Play is off without a daemon (or with one of another user, or too old to
take it) and while the device is not connected; the bar says why next to it ("Play: device not connected").
With a daemon that drives the virtual device (`[device] virtual = true`) while it doesn't run, Play opens it in the
window and plays on it.

While no daemon runs, "Try without a device" starts one with the virtual device on this file (saved first if it is
new) and opens the device in the window, in Play: to set everything up and try it before there is a device. That
daemon ends with the window.

## Test the device

"Test the device", above the drawing, asks the daemon to test the device: the strips light up one after the other
(the sweep), then every strip answers its own controls, on the device and in the drawing, so the two can be compared.
A bar says what each control does:

| Input on a strip | What the strip shows |
|---|---|
| Fader moved | The meter follows the fader. |
| Fader touched, let go | `touch`, `let go` |
| Rec, Solo, Mute, Select pressed | Its LED goes on, flashing, off (`mute on`, `mute fl`, `mute off`). |
| Encoder turned | Changes what the encoder edits, wrapping around, and shows its value. |
| Encoder pushed | The next thing the encoder edits: the position of the ring (`ring 7`), its mode with and without the two LEDs at the ends of the ring (`dot`, `boost`, `wrap`, `spread`, `dot+c` ...), the color of the LCD, the motor fader in steps of 10 % (`fad 60%`). |

Play works on the drawing during the test, and so does the hosted virtual device. The slots go on meanwhile (Home
Assistant still sees them), but show on the device only again when the test ends: a click on the button, closing the
window, a preview "On the device", or the device going away. The footer says why it ended.

## Log

View → Log (Ctrl+L) opens the window **Log**: the log of the daemon that runs, the same records the journal or its
terminal show, at the level the daemon runs with (`-l debug` for more). It works for the service and for a daemon
started in a terminal or an IDE. Like the window Device, it can go to any side or be a window of its own.

- **Colors:** warnings in yellow, errors in red, debug records in the color of hints, the time of each in it too.
- **Level:** shows the records of that level and above.
- **Search:** marks the text in the log, ignoring case, and counts the matches. Enter selects the next one.
- **Follow:** keeps the latest records in view. Scrolling up stops it, scrolling to the end (or the button) starts it
  again.

The window gets the last 1000 records when it opens, then every new one, and keeps the latest 5000. When no daemon
runs, it says so; when the daemon stops, the last records stay, and the window starts over when it is back. A daemon
of an older version has no log for the window: restart it to run the installed version.

## The virtual device

While the window hosts the virtual device, Play is on (see [Select and Play](#select-and-play)).

A bar above the drawing unplugs it and plugs it in again, switches it off and on (the faders go down by themselves,
as on the device), and breaks the touch sensor of faders ("Broken touch"), to try `touchless_faders`. "Close" closes
it, and so does closing the window: for the daemon it is unplugged. What the drawing shows still comes from the
daemon, which is what reached the device.

When the device (`[device] name`) is plugged in while the daemon drives the virtual one, a bar above the drawing says
so. Its button switches to the device:

- **Switch to it** (`[device] virtual = true` in the file): turns `virtual` off, saves the file (after asking, when
  it has other changes) and closes the virtual device. The daemon reloads and takes the device, without a restart.
- **End the trial** (the daemon of "Try without a device"): ends that daemon. Start the service to use the device.
- A daemon started elsewhere with `--virtual-device` only uses the device after a restart without it: the bar says so,
  without a button.

## Preview

Next to Save and apply, a pill says what the device runs: "Saved, on the device", "Unsaved changes" (the device
runs the saved file), "In the GUI, not saved", "On the device, not saved", or what is wrong (e.g. "Not running",
"Not on the device yet"). A click tells it in full, with the path of the file ("Copy the path", "Open the folder") and
the file the daemon reads when that is another one.

While there are unsaved changes, or Simulate is open, the control "Preview" sits next to it. It decides where the
changes (and Simulate, which always includes them) show before they are saved, a moment after each change (undo and
redo too). The file is not written.

- **In the GUI** (the default): the window shows the preview on a **virtual twin** of the device in the daemon. The
  twin is a second, complete set of strips that drives no real sound, voice chat, [Home Assistant](home-assistant.md) or device. The drawing,
  the cards of the page Slots and Play show the twin, with a frame around the drawing. Without Simulate, the twin runs
  the changes in the situation of now: the mode and the states the device has, and the applications, people and
  devices there are. The device keeps running the saved file. The pill says "In the GUI, not saved".
- **On the device:** the device runs the preview, before it is saved: pick it to try the changes for real. The
  drawing shows the device, and the pill "On the device, not saved" ("Sending to the device…" for a moment after a
  change).
- **Off:** the drawing shows the device as it is, running the saved file, for when you can't see the device. The
  changes show nowhere until you save them or pick another place. Opening Simulate moves the preview to In the GUI,
  and ending it back to Off.

The place stays as it is set for the next changes until the window closes; a new window starts with In the GUI.

- **Save and apply** makes it the configuration: the daemon loads the saved file, which is what the preview showed.
- **Back to the file:** another place, closing the window (it asks about unsaved changes as usual, and says when the
  device runs them) or "Revert" brings back the saved file. So does a window that crashed: the daemon goes back to the
  file when the connection of the window ends, or when the window does not answer for 10 seconds. On the device, the
  file also comes back when it changes on disk, or the daemon is reloaded; then the preview goes back to In the GUI
  and the window says why.
- **What the daemon does not take** shows in red under the status bar at the top, and the preview keeps the version
  before. On the device it can't change `[mqtt]` (that takes a save and a restart), nor `[device] name` and `virtual`
  (they take a save). A configuration with problems is not sent at all: the pill says "Paused: problems" until they
  are fixed.
- **Channels, states and slots** are all part of it: a stack changed in the editor shows in the preview as it is.
- **Simulate:** its situation shows where the preview shows. On the device, the device shows the what-if of Simulate
  instead of what really happens: the states and the mode it sets, its channels present or absent, and its people,
  applications and devices (real ones first, so their faders move real audio; made-up ones for the rest, `App 1`,
  `Device 1`). Delays and dwells apply as they really do. The pill says "On the device · simulated". Home Assistant
  never sees it: its slot and state sensors stay as they really are, and nothing of it is kept.
- **One window on the device at a time:** a second window that picks On the device takes over, and the first one's
  preview goes back to In the GUI.
- **Home Assistant:** channels the changes do not have keep their entities in Home Assistant (with their state; only
  nothing drives them), so they are as before once the file runs again. Entities of channels only the changes had are
  removed again when it ends.

The places say why they are off in their tooltips: In the GUI needs a running daemon of your user; On the device
also needs one that reads this file. A daemon from before this feature has neither (restart it to run the installed
version).

## The slots

On the page Slots:

- **The state bar** lists the states and modes: ● on, ○ off, with the override in brackets. A click on one shows what
  turned it on, its override (real, like Home Assistant or `xtouch-daemon mode`: `auto`, `on`, `off`, or for a mode
  picking it and back to the rules), and Simulate with it the other way (nothing changes).
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
  = white, rec = recording`). + adds `auto` at the end, the bin (or Del) removes the candidate picked. Drag a
  candidate, or move it with Ctrl+Up and Ctrl+Down. A slot without candidates shows `auto`.
- **The inspector** starts with the path of the slot's candidates (`Slot 3 › 1 games › 2 apps`: the one picked
  highlighted, ● the one the slot shows, ○ the one it came to that has none left; a click picks one) and a box of
  what goes on: why the slot shows what it shows, a step a line (✗ a candidate passed over and why, → what it shows,
  the same as `xtouch-daemon why 3`), which channel the candidate shows, where else that is used and where it is
  now, or what a pool hands out and from which side. Below it, it edits
  the candidate picked: what it shows (a channel, a pool such as `apps`, `people` or `auto`, `-`), when (the
  [condition](../configuration/slots.md#conditions):
  states violet, channels in `present(...)` teal, a mistake underlined in red with what is wrong in its tooltip;
  typing offers the states, keywords and channels that fit, Ctrl+Space all of them),
  and, under "Look in slot 3", the options of its place (look, on `apps` and `auto` the encoder and the volume range,
  on `people` the look of a person's strip). What the parts do is set on the channel or the pool: "Edit the channel"
  (or "Edit the pool") at the top opens it on the page Channels. An option left unset is as on the channel, or as in
  the pool: the field shows that value ("As on the channel: red"), and the button next to a set option unsets it
  again. A pool of channels has no options here: its channels bring their own look.
- **Controls of slot 3**, at the end of the inspector, edits [`[controls]`](../configuration/slots.md#controls-and-the-chord)
  of the slot: the parts that act the same whatever the slot shows. "Add a part" claims one (the fader, the encoder,
  Select, Rec, Solo, the meter, the color or the line of the LCD); only the parts an entry sets show. Each has the
  field it has on the page Channels. The bind button gives the fader, the encoder, the meter, the color and the line
  to Home Assistant, to an entity of it or to a program (the fader and the encoder also to a custom channel). A
  button takes its press (also a service of Home Assistant),
  its LED or both. Without a press, a press goes to what the slot shows; without an LED, the LED shows what the press
  does. When takes a condition of states and modes. Id names the entities in Home Assistant (shown once a part is in
  Home Assistant). "Add controls" adds another entry, e.g. for another `when`: the first whose `when` holds acts, and
  the arrows move an entry up or down. A problem shows at its field.

Clicking a strip in the window Device (or Left, Right, Home, End) picks its card, with the candidate it shows.

**Simulate** shows what the slots would show in another mode, with other states on, with channels absent (`auto
plays`: an application plays; `people fill`, `apps fill`: as many as there are slots), or with so many people in the
call and applications that play (the two counts; the strips show their names). Simulate includes the unsaved changes
and shows where the [preview](#preview) shows: in the GUI, on the virtual twin of the device in the daemon, or on the
device. A frame goes around the drawing in the window Device, a bar of what-ifs replaces the state bar, and the
drawing, the cards and the box of the inspector show it, and Play can operate it. Simulate needs a running daemon of
your user: without one its button is off and says how to start it. Esc, or Simulate again, ends it.

## Editing options

The forms come from the options of the configuration, so every option has a field. The options of a [channel](../configuration/channels/index.md) are in
cards in the order of the device, from top to bottom: what it controls, the [encoder](../configuration/strip/encoders.md), the display, the buttons (Rec,
Solo and Select each with what a press does, what a hold does and what the LED shows; unset, each shows the default
of the type), the fader and the meter, then those about slots (`tags`, `in_pool`, ...).

The cards of the encoder, the display, the buttons and the fader have a drawing of that part of the strip, which shows
what the options do on the device in a few steps (‹ and › go through them), each with a caption: the ring as the encoder turns and is pushed, the LCD while audio
plays (with the label of each choice), while muted and with nothing to control, which LEDs light while audio plays, an application records or the
strip is muted and after a press or a hold of each button that does something, and the volume at the bottom, at the 0 dB mark and at the top of the fader, with what the meter shows
there. It follows the values in the form at once, saved or not, at the step shown.

- switches for on/off options, numbers with their ranges, choices, color swatches, lists as chips, masked fields for
  secrets, and file pickers;
- the help of each option under its field, with its default and, where the documentation explains more, a
  "Learn more" link to that section; a button sets the option back to its default;
- `choices` (and `profiles`) as a list of entries, each with its label, its device and what it needs. The pencil or a
  double click opens an entry with its fields, with the devices, the sound cards and the profiles of its card
  to pick from; the card and the profile are under "Switch the sound card first". Drag ⠿ (or Ctrl+Up/Down) to change
  the order, which is the order Select goes through them. While a channel has `choices`, `device` and `profiles` are
  hidden, and the other way around: a channel has one or the other;
- the meter as one choice: the level before the fader, after it, or off;
- a bind button next to each part that can be [bound](../configuration/strip/bindings.md) (the fader, the encoder,
  the LCD, the color, the meter, `present`): "Not bound", "Home Assistant" (with `[mqtt]`), "An entity" (with
  `[homeassistant]`) or "A program". "A program" shows the options of the program under the part, e.g. `set`,
  `watch` (or `poll` and `every`), `min` and `max`; "An entity" those of the [entity](../configuration/strip/bindings.md), e.g. `entity`,
  `attribute`, `min`, `service`. A problem in one of them shows under its row. Set back to "Not bound", the part does
  what its type says again;
- the field of an entity suggests the entities of Home Assistant (see [below](#suggestions-from-home-assistant)), the
  field of an attribute those of the entity picked, with their values now. An unset option says what the domain of
  the entity does, e.g. "default: 255, of a light" for `max` of a light, or "default: light.turn_on, of a light" for
  `service`. `data` is typed as an inline table, e.g. `{ brightness_pct = 50 }`;
- in the lists of a button's press, hold and LED on a channel page, typing `run: ...`, `watch: ...` or `poll: ...` binds the
  button to a program. `service:` (in the list of a press or a hold) calls a service of Home Assistant, `entity:` (in
  the list of an LED) shows an entity: their options (the service, the entity, `data`, `attribute`) show under the
  list. Places and pools take the words of the lists only;
- for choices, what the chosen value does (e.g. `recording` for the Rec LED), and each value says it as a tooltip in
  the list;
- the mouse wheel scrolls the page, also over a number or a choice: it never changes a value;
- the errors next to the options they belong to, with the same messages as `xtouch-daemon check-config`. The
  problems button in the footer lists them all; a click opens the page of the problem. An unknown option can be
  removed from there.

`[mqtt]` can be added and removed on its page. Above its options, the page shows how the daemon's connection is
doing (or that the daemon runs without the section, which it reads only when it starts), and "Test connection"
connects once with the settings as they are in the editor, saved or not, and says what is wrong if that fails.

The page "Home Assistant API" (`[homeassistant]`) does the same for the API of Home Assistant: how the daemon's
connection is doing (it connects only while a part shows or sets an entity), and "Test connection", which logs in
with the address and the token in the editor and says the version of Home Assistant and how many entities it has, or
what is wrong: a token it refuses, an address where nothing answers. The entities it found are the suggestions then.

## Suggestions from Home Assistant

With `[homeassistant]`, the field of an entity suggests the entities of Home Assistant: the window reads them with the
address and the token in the editor, saved or not, when a field of an entity shows, and again a minute later or with
other settings. Each line has the icon of its domain, the name of the entity, its state now (e.g. `21.5 °C`) and
below it its id. A click into the field or the focus opens the list inside the window; typing narrows it down, by any
part of the id or the name. Up and Down move in it, Enter or Tab picks, Esc closes it. The field of an attribute
suggests the attributes of the entity picked.

Without suggestions, a line under the field says why: no `[homeassistant]`, a problem of its settings, or that the
window can't reach Home Assistant (with what to check, and whether the daemon reaches it). "Settings" opens the page
of the section. You can always type the id.

The window connects on its own, with the token in the editor, not through the daemon. With `token_env`, the token is
in the environment of the service, and the window has none: the test fails and there are no suggestions. Start the
GUI with the variable set (e.g. `HA_TOKEN=... xtouch-daemon gui` for `token_env = "HA_TOKEN"`), or use
`token_file`.

## Suggestions from the sound server

The GUI reads the sound server and suggests what it has. A click into a field opens the list, and typing narrows it
down (by any part of a name or a description, or a pattern with `*` and `?`), with the parts that match highlighted;
each line says what it is, where it is known from (the default, the active profile, a preset) and below it the name
that goes into the option. Under `device`, `card` and `profile` of a choice, a line says what the value matches, e.g.
"Matches 2: ..." for `bluez_output.*`, or "Matches nothing known" (a device can come later).

| Option | Suggestions |
|---|---|
| `device` | The outputs or inputs by node name, with their descriptions; the default is marked. Then the devices that another profile of their sound card would make (e.g. the digital output while the card is in its analog profile): picked for a choice, they fill in its card and profile. Then the devices the daemon saw that are not there now, e.g. Bluetooth headphones that are off ("seen 3 days ago"); Delete in the list forgets one. |
| `card`, `profile` of a choice | The sound cards (by description, or the devices they have), and the profiles of the card of the choice. |
| `profiles` | The profiles of the sound cards of those devices; the active one is marked. |
| `match`, `exclude` of `[pool.apps]`, `apps` and `recording` of a state | The [presets](../configuration/presets.md) (`@browsers`, ...) first, then the names and binaries of the applications that play. A preset's tooltip tells what it stands for; its chip is outlined. |
| `processes` of a state | The presets for processes. |
| `[aliases]` | The names of the applications that play. |
| `person` of a `person` channel | The people in the voice chat now, as the running daemon tells them. |

The pill "Sound server: ..." says how much the GUI read; a click lists the outputs, inputs and applications, with
"Read again" (also the refresh button next to it), e.g. after you started an application. Without a
sound server, type the names by hand. The people of the voice chat come from the daemon's live view: without a
running daemon (or nobody in the channel), type the names by hand.

## Undo

Every edit can be undone: Ctrl+Z undoes, Ctrl+Shift+Z redoes. That includes removing a channel and reverting the file,
so neither asks first. Typing into one option is one step. Ctrl+Z undoes in the document also while a text field has
the focus.

Closing the window with unsaved changes asks whether to save them.

## Keyboard

Help → Keyboard shortcuts lists the keys. The keys of the menus follow the desktop; these are the usual ones:

| Keys | What they do |
|---|---|
| Ctrl+S | Save and apply |
| Ctrl+Z, Ctrl+Shift+Z | Undo, redo |
| Ctrl+1 to Ctrl+4 | Slots, Channels, States, Settings |
| Ctrl+L | Open or close the window Log |
| Del (or Backspace) | Remove the candidate, channel, pool or state picked, as its button Remove does |
| Ctrl+C, Ctrl+X, Ctrl+V | Copy, cut, paste it |
| Ctrl+D | Duplicate it |
| F2 | Rename it: the focus goes to its id (on a candidate: to Shows) |
| Ctrl+Up, Ctrl+Down | Move the candidate picked, or the entry of a table |
| Left, Right, Home, End | Pick a strip of the drawing; Ctrl+Left, Ctrl+Right move its slot |
| Esc | End Simulate, close a popover |

Del, Ctrl+C and the others of the menu Edit are for the list that has the focus: the cards on Slots, the lists on
Channels and States. In a field they edit its text. Copy puts the entry on the clipboard as in the file: a channel as
`[channel.mic]` with its options, a candidate as the value of the list of its slot (`"browser if call"`). Paste takes
that back, also from a text editor, and gives a channel, pool or state whose id is taken one after it (`mic_2`). A
candidate goes after the one picked; channels, pools and states go at the end.

## Save and apply

"Save and apply" (Ctrl+S) writes the file and reloads the daemon:

- It saves only a file without problems: the daemon would not take one with problems.
- Unchanged values keep their place and their comments, and a stack keeps its form (a string, a list, tables) where
  it did not change. The file is written in place, so a symlinked configuration stays one.
- It reloads the running daemon when that reads the saved file: the service, or one started from a terminal or an
  IDE.
- Without changes it is there too while the daemon runs another version of the file, e.g. one edited outside the
  GUI: then it only reloads the daemon.
- A changed `[mqtt]` section is not reloaded at all: the window offers "Restart the service" for the service;
  restart a daemon that runs elsewhere where it runs. A changed `[device] name` or `virtual` is: the daemon switches
  to that device.
- It then tells whether the device runs the saved file: "The device runs the saved file", or "The device does not run
  the saved file yet". If that stays, the daemon did not take the file, and its log says why (View →
  [Log](#log), or `journalctl --user -u xtouch-daemon`).

"Revert" drops the changes and reads the file again (Undo brings them back).

### Changes of the file on disk

The window notices when something else changes the file while it is open: an editor, a script, `init-config`.

- Without unsaved changes it reads the file again. The page and the strip that were picked stay. Undo goes back to
  the version before, as changes to save.
- With unsaved changes a bar above the page asks. **Reload** reads the file and drops the changes (Undo brings them
  back). **Keep mine** goes on with them, and the next save overwrites the file.
- A file that can't be read (e.g. a TOML error) leaves the window as it is, and the bar says why. Once the file is
  fixed, the window reads it.
- "Save and apply" never overwrites a change it did not show: if the file changed since the window read it, it asks
  first (Overwrite, Reload or Cancel).

Next: [Commands](../reference/commands.md) for the same things on the command line, [Troubleshooting](troubleshooting.md).
