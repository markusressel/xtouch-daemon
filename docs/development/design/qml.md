# Design: the GUI in Qt Quick

The GUI moves from Qt Widgets (`gui/qt`) to Qt Quick (`gui/quick`): QML draws the window, and Python keeps deciding.
With QML, everything that changes can move. A value animates to its new one, a row that comes grows in while the rows
under it slide along, and a page fades through to the next. Qt Widgets can only fake that with pictures of widgets
(see [Motion](motion.md)).

While the migration runs, `XTOUCH_GUI=quick xtouch-daemon gui` starts the new window, and the widgets stay the
default. When every part is done, the window in Qt Quick becomes the only one and `gui/qt` goes.

## Layers

The layers stay as they are (see [the architecture of the GUI](../architecture/gui.md)):

- `gui/domain` decides everything, without Qt. It doesn't change for QML.
- `gui/quick` holds the backends: a `QObject` per part of the window, which turns the domain into properties, lists
  and slots for QML, and passes edits back to the `Editor`.
- `gui/quick/qml` holds the QML, which only shows what the backends have and calls their slots.

QML keeps no logic of its own beyond how things look and move. A decision in QML (what a row shows, whether a
button is enabled, what a click changes) belongs in a backend, where the tests and the coverage reach it.

## Files

| Part | Python (`gui/quick/`) | QML (`gui/quick/qml/`) |
|---|---|---|
| The engine, the theme, the icons | `engine.py`, `theme.py`, `icons.py` | `XTouch` (the singleton `Theme`) |
| The style of Qt's controls | | `XTouchStyle` (`Button`, `TextField`, ...) |
| Our own controls | | `XTouch.Controls` (`Card`, `Pill`, `Chip`, `Popover`, `Reveal`, ...) |
| Lists that change row by row | `models.py` (`KeyedListModel`) | |
| The application | `app.py` (`App`, `Dependencies`, `run_quick`) | |
| The window: menus, footer, dialogs, the service, the file, zoom, log | `window/` (`Shell`) | `XTouch.Window` (`Main`, `Rail`, `AppMenuBar`, `Footer`, `LogPanel`) |
| The drawing of the device | `device/` (`DevicePanel`) | `XTouch.Device` (`DevicePanel`) |
| The forms made from the models | `forms/` | `XTouch.Forms` |
| The pages | `pages/` (`SlotsPage`, `ChannelsPage`, `StatesPage`, `SettingsPage`) | `XTouch.Pages` |

`App` is the root object: `Main.qml` has it as its required property `app`, and hands it to each part. `App` has
the `Editor` (`app.editor`), the dependencies on the outside (`app.deps`), the page shown, and a backend per part
(`app.shell`, `app.device`, `app.slots`, `app.channels`, `app.states`, `app.settings`).

The parts meet at a few places, which the foundation fixes:

- Every page backend is a `PageBackend` (`pages/base.py`). The Edit menu asks the page shown what it can do
  (`editable`, a list of `cut`, `copy`, `paste`, `duplicate`, `remove`, `rename`) and does it (`edit(action)`).
  The list of problems shows an option with `reveal(path)`.
- The slot picked is `app.slots.slot` (1..8, 0 for none). A click on a strip of the drawing calls
  `app.slots.selectSlot(n)`, and the drawing marks the strip of `app.slots.slot`.
- The window shows a page with `app.showPage(name)`; `app.page` is the page shown.

## Rules

- **Our controls only.** `import QtQuick.Controls` gives the controls of our style (`XTouchStyle`): they take their
  colors, sizes and motion from `Theme`. A control we need beyond Qt's goes into `XTouch.Controls`, so every page
  has the same one. No colors or sizes as literals: `Theme.colors.*`, `Theme.space.*`, `Theme.radius.*`,
  `Theme.controlHeight`, `Theme.fontSize.*`.
- **Everything moves, through the theme's durations.** A value that changes animates with a `Behavior` of
  `Theme.fade` (a color, an opacity, a text through `FadeText`) or `Theme.resize` (a size, a position, something
  that comes and goes, with `Easing.OutCubic`). A row that comes and goes is an item of a `ListView` with `add`,
  `remove` and `displaced` transitions, or a `Reveal`. The durations are 0 while `Motion.enabled` is off, in tests
  and screenshots, so a test sees the end at once.
- **Lists change row by row.** A list whose rows change is a `KeyedListModel`: `show(rows)` with a key per row
  that stays the same while the row is the same thing. A delegate then stays and animates its new values, instead
  of being made anew.
- **No popup windows.** A `Popup`, a `Menu`, the list of a `ComboBox` and a `ToolTip` stay items of the window
  (`popupType: Popup.Item`, which our style sets). The fixture `no_popups` fails a test in which a popup window
  shows. A second window of our own (a panel moved out of the window) is a `Window`, not a popup.
- **Names for the tests.** An item a test needs has an `objectName`: `rail_slots`, `page_channels`, `card_3`,
  `row_<key>`. `tests/support/quick.py` (`Ui`) finds items by it, clicks them, types into them and presses keys.
- **Keyboard first.** Everything that can be clicked can be reached with Tab and pressed with Space or Enter; a
  popover takes the focus and gives it back to its anchor when it closes. Shortcuts are `Shortcut`s or `Action`s of
  the window.
- **The wheel never changes a value** under the mouse: our `SpinBox`, `Slider` and `ComboBox` take the wheel only
  while they have the focus. A list scrolls with the wheel at the speed of the desktop.

## Tests

`tests/gui/quick/` drives the window offscreen with Qt's software renderer. The fixture `ui` is a window with a fake
systemctl, a fake sound server and the configuration of `tests/support/gui.py`; `make_ui(**dependencies)` makes
one with others. A test of a backend that needs no window builds the backend alone.

The tests of the widgets (`tests/gui/qt/`) say what the window does. Each part ports the tests of its widgets to
its QML: the same behavior, checked through the window in Qt Quick. When the widgets go, their tests go with them.

## The parts of the migration

Each part works in its own files (the table above), so the parts can be done side by side:

1. **Foundation**: the engine, the theme, the style, the controls, the window with its rail and empty pages, the
   test harness.
2. **The window**: the menus and their shortcuts, the footer (problems, sound server, status, pills, the preview,
   undo, redo, revert, save and apply), dialogs, the service and the file on disk, the zoom, the theme, the log,
   where the panels are and what the window remembers.
3. **The drawing of the device**: the strips painted by `QQuickPaintedItem`s with the painting of `gui/qt/preview`,
   the panel with the virtual device, hands, previews of the controls.
4. **The forms**: a row per option, its field by the kind of the option, the help, the problems.
5. **The pages**: Slots (the cards, the inspector, Simulate), Channels, States, Settings.
6. **The end**: the window in Qt Quick is the default, `gui/qt` goes, the screenshots and the docs follow.

## The drawing of the device

The drawing of the 8 strips is `gui/quick/device/`; its QML is `qml/XTouch/Device/`. The painting is the one of the
widgets (`gui/qt/preview/painting.py` with its pixmap caches), so the strips look the same in both toolkits.

- **Strips as items.** `StripItem` is a `QQuickPaintedItem` that paints a `PaintedStrip`, a `StripView` of the
  widgets that gets its font, focus, hover and pixel ratio from the item instead of from a widget. The mouse, hover,
  wheel, keys, cursor and tooltip arrive in the event methods of the item and go to the same code as before. A hidden
  `HostWidget` is the parent that `StripView` needs, so the application must be a `QApplication`. The painting still
  reads the theme mode from a global of the widgets (`style._current_mode`); every item sets it before it paints.
- **`Drawing`** is the model of the whole drawing: where the strips sit (`positions`, `places()`), the size and scale,
  selection, Play and Select, drag to move a slot, the blink, the faces and the hand. `DrawingStage.qml` binds eight
  `StripItem`s to it. The strips glide aside while one is dragged with a `Behavior` of `Theme.resize`; the right-hand
  click menu is an in-window `Menu`.
- **`DevicePanel`** (`app.device`) is the backend of the page: the bar (Select and Play, the pills of the live view,
  the mode and the virtual device, the test), the live preview with its places (`places`, `setPlace`), the test of the
  device, the virtual device hosted in the window and the trial without a device. The pills open `EntriesPopover.qml`,
  which shows what `popover(kind)` returns (`live`, `modes` or `virtual`); `activate` and `toggle` run its buttons.
- **What the shell gives it.** `say(text)` and `warn(title, text)` default to the signals `message` and `warning`; the
  window sets them to its status line and dialogs. It tells the shell which slot was picked (`picked`, `unpicked`,
  `slotMoved`). The window calls `shutdown()` when it closes, `refresh_service()` when it found the daemon again, and
  `keep_trying_for_next_window()` to hand a running trial to the next window.
- **Previews of controls.** `PartPreview.qml` takes a `model`, a `PartPreviewModel(part)` with `part` one of
  `encoder`, `display`, `buttons` and `fader`. Call `model.play(frames)` with `gui.domain.demos.scene(...)` whenever
  the options change; the step shown stays. `cardColor` and `edgeColor` give the colors the corners and the edge are
  drawn in.
- **Screenshots.** `gui/quick/device/render.py` draws the strips without a window: `Scene` (one drawing at a scale,
  pixel ratio and theme), `render_drawing` and `render_strip` return a `QImage`.
- **Not done here.** Esc ends Simulate only while a strip has the focus; the slots part owns Simulate and its Esc.
  Dialogs and the process of the trial (`trying`) depend on hooks of the shell.

## The page Slots

Files: `gui/quick/pages/slots*.py` (`slots.py` is the backend `SlotsPage`; `slots_data.py` is pure data: rows, chips,
crumbs, the "why" steps) and `qml/XTouch/Pages/Slot*.qml`. The Python types of the page (`ConditionHelper`,
`SoundBadge`) are registered in `XTouch.Slots`; the page imports it.

- **What the page reaches** (the daemon's snapshot, requests, the twin, the sound server) is a `Live` dataclass in
  `SlotsPage.live` (or `deps.extra["slots_live"]`). The window sets `live`, calls `show_live(snapshot)` for each
  snapshot (it also feeds the clock of the sound badges) and `show_place(note)`; the signal `simulated` tells the
  window to start or end the twin. The drawing of the device picks with `selectSlot` and `slot`.
- **Cards** are `SlotCard`s with a `MovableRows` (a `KeyedListModel` that can move a row). A row's key is the
  candidate as the file has it, so a state change updates a row in place and only a real change inserts or removes
  one. A drag moves the rows aside by offset, then `reorder` writes the file; Ctrl+Up/Down use `moveCandidate`.
- **Rich text** keeps color tokens (`@state`, `@channel`) that `SlotFadeText` resolves against `Theme.colors`, so a
  theme change recolors it live. Links get their color from their own style (rich text ignores `linkColor`).
- **Wheel**: `SlotScroll` takes the wheel with a `WheelHandler` (a notch is `wheelScrollLines` x 20 px) and glides
  to the goal, so the next notch adds to it. It never flicks: rows are dragged.
- **Simulate** shows a panel (`SlotWhatIf`) under the bar; Esc ends it (a `Shortcut` of the page).
- **Edit menu**: `PageBackend.editable` calls the overridable `editable_actions()` (new, `[]` by default); the page
  answers by the card that has the focus.
- **Placeholders for the forms**: `SlotPlaceForm.qml` (input: `optionPath`, `strip`, `allowed`, `pick`) is the
  option rows of the place of a candidate; `SlotControlParts.qml` (input: the entry's `path` and `parts`) is the rows
  of the parts of a control entry. Both write through `SlotsPage.setPlaceOption` and `SlotControls.setOption`.
- The share between the cards and the inspector is not remembered yet.

## The forms

`gui/quick/forms/` (Python) and `qml/XTouch/Forms/` (QML) make a form from the models, with one recursive row and no
code per option. The page Settings (`pages/settings.py`) is the first user; the pages Channels and States show their
forms the same way.

**In Python.** A `Form` is a list of rows over one place of the document:

```python
form = channel_form(forms_of(app), "output")   # the options of a channel of the type; `pool_form(...)` for a pool
form.retarget(("channel", "out"))              # the channel it shows now: the rows change in place
```

- `forms_of(app)` is the `FormContext` of the window: the sound server (`set_audio(state)`), the daemon's state
  (`snapshot`, `known`, `send`) and the entities of Home Assistant. The shell gives it what it knows; without it, the
  context reads the sound server in a thread on first use.
- A `RowSpec` binds an option to its suggestions, placeholder and link; `strips.py` makes them for a strip type. A
  page with other options builds its own `Form(context, specs, base=..., present=...)`.
- The rows are `form.rows`, a `FormRowsModel` with the roles `key`, `spec` (what an option is: its name, kind,
  choices, default; it changes only when the model does) and `info` (what it shows now: value, placeholder, problems;
  it changes with the document). A value that changes updates `info` in place; it never rebuilds a row.
- Edits go through `form.setValue(name, value)` and `form.reset(name)`: one step to undo per edit, typing in one
  option merges. Loading never writes. A form that is not `active` waits and shows the latest on `active = true`.
- `form.rest` has the problems no row shows, `form.reveal(name)` asks the view to scroll to a row and focus it.

**In QML.** `FormView { form: theForm }` shows a form. Rows come and go with `Reveal`, problems and help fade and
expand. `UsedBy` (`context.usedBy(where, none)`) and `HistoryBars` (`context.historyBars(history)`) are the small
pictures of a channel and a state. `PartPreviewPlaceholder` stands where the preview of a group of parts (display,
encoder, buttons) belongs: the part of the drawing of the device replaces it with its `PartPreview`.

**Settings.** `SettingsPage` has `entries` (the navigation), `sections` (a backend per section: `form`, `present`,
`add()`, `remove()`, `live`), `aliases`, `current`, `showSection(name)` and `reveal(path)`. The shell calls
`show_live(snapshot)` with the daemon's snapshots. The broker test and the plugin installers run in threads
(`pages/settings_support.py`), and only the latest result of a test shows.
