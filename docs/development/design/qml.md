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

## The window

`window/shell.py` (`Shell`, `app.shell` in QML) holds everything around the pages. The decisions that are not obvious:

- **Menus are data.** `window/menus.py` describes File, Edit, View and Help (text, keys, description, check state) and
  `AppMenu.qml` builds them. The same data gives the shortcuts (`Shortcut`s of the application, so they work in a text
  field too) and the popover of the keys. The window's undo wins over the undo of a text field through a
  `ShortcutOverride` filter (`window/keys.py`).
- **Dialogs are in the window.** `Dialogs.ask()` shows `DialogHost.qml` and waits in a nested event loop, as
  `QMessageBox.exec` did, so a flow such as save, ask about overwriting, save again stays one function. Tests give the
  window a `FakeDialogs` that answers at once.
- **Panels.** The device and the log each have a `Host` per side of the configuration; a host shows while its panel is
  there. A split does not follow items that are reparented in and out, so the panels are built once and move between
  hosts, the window of their own (`PanelWindow`, a QML window, never a popup) and a parking item. Place, visibility
  and size are in `QSettings` (`panels/<name>/...`); the View menu moves them.
- **Zoom** keeps the widget design: Qt scales a whole application at its start, so `run_quick` loops, one application
  per zoom, and a `Session` carries the document with its history, the page, the geometry and the trial daemon.
- **Pill popovers** are `Details` (Python rows) shown by `DetailsPopover.qml`; they rebuild while open.
- **The log** fills the `QTextDocument` of a `TextArea` from Python and asks the daemon only while the panel shows.
- **Hover tips** come from one event filter on the window: the first paragraph of the `tip` of the item under the mouse.
