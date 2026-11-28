# GUI

`xtouch-daemon gui` is an optional editor for the configuration file, in the subpackage `gui` and the extra of the same
name, like the GUI of [openhasp-config-manager](https://github.com/markusressel/openhasp-config-manager). The daemon
itself does not import it. How to use it: [GUI](../../guides/gui.md).

## Layers

- **Toolkit-free domain, thin Qt Quick.** `gui/domain` decides everything, `gui/quick` turns it into properties and lists, and the QML in `gui/quick/qml` only shows it and passes edits back:
  - `slots_document`: the file as plain values, validated with `parse_config()` (the messages of `check-config`), and
    saved;
  - `slot_stacks`: the stacks of the slots as rows to edit; `simulate` and `slots.outcomes`: what other modes and
    states would show;
  - `looks`: how the live view draws each strip; `status`: whether the device runs the saved file;
  - `sources`: suggestions from the sound server; `problems`: which page shows a problem;
  - `apply()`: reload, restart or "the daemon does not run".
- **One source of truth: the `Editor`** (`quick/editor.py`) holds the document, its history and its validation. Views read
  from it and change the document only through it, so nothing keeps a copy that could go stale. Its signal
  `changed(Change)` comes once per edit, after the document was validated once.
- **Changes say what changed.** A `Change` (`gui/domain/changes.py`) has a `Scope` and, for some scopes, a path. Each
  page's `show_document(change)` updates only what that scope touches.

  | Scope | What changed |
  |---|---|
  | `VALUE` | A value in place; the field that made it shows it already. |
  | `CHANNELS`, `STATES` | A channel or state was added, removed, renamed or duplicated. |
  | `SLOTS` | A candidate of a stack was added, removed, moved or changed. |
  | `SECTION` | A section was added or removed. |
  | `ALIASES` | The list of aliases. |
  | `DOCUMENT` | Anything (undo, redo, revert). |
  | `FILE` | The file was written, so the document is the same. |

## The window

The window is Qt Quick. Python holds the decisions in backends, QML only draws and moves. A decision in QML (what a
row shows, whether a button is enabled, what a click changes) belongs in a backend, where the tests and the coverage
reach it.

| Layer | Where | What it does |
|---|---|---|
| Backends | `gui/quick/` (`app.py`, `window/`, `device/`, `forms/`, `pages/`) | One `QObject` per part of the window, with properties that notify, slots QML calls, and `KeyedListModel`s for lists that change row by row. |
| QML | `gui/quick/qml/` | The modules `XTouchStyle` (the style of Qt's controls), `XTouch` (the singleton `Theme`), `XTouch.Controls` (our own controls), `XTouch.Window`, `XTouch.Device`, `XTouch.Forms` and `XTouch.Pages`. |

- **One root, `App`.** `App` (`quick/app.py`) is the required property `app` of `Main.qml`. It has the `Editor`, the
  dependencies on the outside (`Dependencies`: the service, the sound server, the daemon, the dialogs), the page
  shown, and a backend per part: `app.shell`, `app.device`, `app.slots`, `app.channels`, `app.states` and
  `app.settings`. `run_quick` makes the application, the backends and the engine, and `close_window` ends them in the
  right order: the QML first, then the backends it binds to.
- **The shell holds the window.** `Shell` (`quick/window/shell.py`) owns the live view, the live preview, the daemon
  found, the virtual device the window hosts, the menus (as data in `menus.py`), the footer, the dialogs, the service
  and the file on disk. The panels and the pages only read it and call it.
- **Pages by what they edit.** A rail has the pages Slots (a card per slot with its stack, an inspector for the
  candidate picked, why it shows, Simulate), Channels, States and Settings (`[device]`, `[behavior]`, `[aliases]`,
  `[mqtt]` as "Home Assistant", `[voip]`). Every page is a `PageBackend`, so the menu Edit asks the page shown what it
  can do. Slots, Channels and States are two panes with a handle (`PaneSplit`) that keeps its share in `QSettings`.
- **Panels, not docks.** The drawing of the device (`DevicePanel`) and the log are panels beside the configuration:
  above, under, left or right of it, or in a window of their own (a QML `Window`, never a popup). View → Device at and
  View → Log at move them; place, visibility and size are in `QSettings` (`panels/<name>/...`). A split does not
  follow items that are reparented in and out, so each panel is built once and moves between its places.
- **The drawing.** `Drawing` (`quick/device/drawing.py`) decides where the 8 strips sit and what they show. A
  `StripItem` is a `QQuickPaintedItem` that paints a `StripPainter` (`device/strip.py`): plain `QPainter` code with
  pixmap caches (`painting.py`), no widget. The item passes the mouse, hover, wheel and keys on. `device/render.py`
  paints the drawing without a window, for the screenshots and for tests that look at pixels.
- **The log of the daemon.** The log panel asks the daemon for its log over the live view only while it shows (see
  [Live view](live-view.md#log)). What it keeps, filters and searches is in `gui/domain/log.py`.
- **Previews of the controls.** `gui/domain/demos.py` makes a short scene per part of a strip from the values in the
  form; `PartPreview.qml` shows it with a `PartPreviewModel` cut to the part. See
  [Design: previews of the controls](../design/control-previews.md).
- **Undo instead of questions.** `History` (`gui/domain/history.py`) keeps the states of the document before every
  edit, so removing a channel or reverting the file asks nothing and Ctrl+Z brings it back. Typing into one option is
  one step. The undo of the window wins over the undo of a text field (a `ShortcutOverride` filter,
  `window/keys.py`).
- **Zoom needs a new application.** Qt scales a whole application when it starts (`QT_SCALE_FACTOR`), so a new zoom
  ends the window and `run_quick` starts the next application, which goes on where this one was (`Session`: the
  document with its history, the page, the place of the window, the daemon of "Try without a device").

## Forms

- **From the models.** `gui/domain/schema.py` reads the options of every section and channel type from the pydantic
  models: the type picks the widget (switch, number, choice, color swatches, list chips, masked secret, file), the
  attribute docstrings become the help, `Field` constraints the ranges, `Meanings` next to a choice
  (`config/values.py`) say what each value does, and `Presets` on a list of names makes it suggest the presets of its
  kind. A new option or channel type needs no GUI code; a test fails for an option without help or a value without a
  meaning. `gui/domain/docs.py` holds the "Learn more" links into this site, and a test checks each against the
  headings of `docs/`.
- **In the order of the device.** A channel's form lists its options from top to bottom like its strip: what it
  controls, the encoder and its ring, the LCD, the meter, the buttons, the fader and the range of the volume, the
  `id`. This is `STRIP_OPTION_ORDER` in `gui/domain/schema.py`, apart from the order of the fields in `config/`; a
  test fails for an option without a place in it.
- **The comments stay.** Saving writes the changes into the TOML document with tomlkit: unchanged values keep their
  place, their comments and their form (a stack as a string, a list or tables), and a renamed channel keeps its
  table. The file is written in place, so a symlinked configuration stays one.
- **Nothing pops up.** A popup window grabs the keyboard and the mouse, on X11 the whole display, so a screenshot key
  would do nothing while it is open. A `Popup`, a `Menu`, the list of a `ComboBox` and a `ToolTip` stay items of the
  window: our style sets `popupType: Popup.Item`. Details a click away are `Popover`s of `XTouch.Controls`. The
  fixture `no_popups` of the GUI tests fails a test in which a popup window shows.
- **The keyboard reaches the popovers.** Everything that can be clicked can be reached with Tab and pressed with
  Space or Enter. A popover takes the focus, Tab goes on to its buttons, and when it closes the focus goes back to its
  anchor. The wheel never changes a value under the mouse: our `SpinBox`, `Slider` and `ComboBox` take it only while
  they have the focus.

## Drawing and updating

- **Lists change row by row.** A list whose rows change is a `KeyedListModel` (`quick/models.py`): `show(rows)` with
  a key per row that stays the same while the row is the same thing. A delegate then stays and animates to its new
  values, and only a real change inserts or removes a row.
- **Built when first shown.** The page Channels builds the form of a channel type (or a pool) the first time it
  shows, and keeps it; a background build makes the others afterwards. Most types never show in a session, and
  building all of them took most of the start of the window.
- **Forms from the models.** A `Form` (`quick/forms/form.py`) is a list of rows over one place of the document. Its
  rows are a `FormRowsModel` with `spec` (what an option is, which changes only when the model does) and `info` (what
  it shows now, which changes with the document); a value that changes updates `info` in place and never rebuilds a
  row. `FormView` shows it.
- **One visual system.** `Theme` (`quick/theme.py`, `gui/domain/tokens.py`) holds the design tokens: the colors of
  the dark and the light theme (text at 4.5:1 or more and the outlines of controls at 3:1 or more on every surface,
  WCAG 2.2 AA, checked by the tests), a 4 px spacing scale, radii, the height of controls, a type scale relative to
  the desktop font, the colors of the device for the drawing (the same in both themes) and the durations of the
  motion. QML takes them as `Theme.colors.*`, `Theme.space.*` and `Theme.fade`, never as literals. See
  [Design: motion in the GUI](../design/motion.md).

## The daemon

- **Found, not guessed.** `xtouch-daemon run` writes `$XDG_RUNTIME_DIR/xtouch-daemon.json` (its process id, its
  configuration file, whether systemd started it) while it runs (`system/instance.py`), so the GUI finds it wherever it
  was started, and a second daemon names the one that has the device.
- **Applying a file.** A saved file is reloaded (SIGHUP) only when the daemon reads that file. A changed `[mqtt]` needs
  a restart, since a reload doesn't take it (another `[device] name` or `virtual` it does: `Surface.use`). The GUI
  restarts only the service: `systemd.Service` (shared with `install-service`) reads the state of the unit and
  installs, starts and restarts it.

## Errors and signals

- **An error is no crash.** PyQt ends the program (a core dump) on an exception in a slot or in a method Qt calls (a
  paint) while `sys.excepthook` is Python's own. `run_quick` installs `quick/errors.py` first: such an error is
  logged with its traceback, and the window says it in its status line and goes on.
- **Qt's messages are in the log.** `quick/qtlog.py` sends what Qt says (QML warnings, a failed binding) to the logger
  `xtouch_daemon.qt`. A window that opens, shows every page and closes logs nothing; a test checks that.
- **Ctrl+C and SIGTERM wait for the event loop.** Python runs a signal handler between any two bytecodes, e.g. in a
  paint or while the window is built. The handler of `run_quick` (`QuitWindows`), installed before anything of Qt, only
  notes the signal; a timer of the event loop closes the windows, which ask about unsaved changes, and not while a
  dialog asks already.

## PyQt6 and QtAwesome

The same as openhasp-config-manager, so the tools look and work alike. The wheels carry Qt itself, so
`uv tool install` needs no system packages (GTK 4 through PyGObject needs the system libraries and a compiler). Qt
Quick draws the window and animates it; `QPainter` paints the drawing of the device; QtAwesome gives the icons
(`image://icon/<name>`). The application is a `QApplication` only for the native file dialog of a path field.

## Tests

`tests/gui/quick/` drives the window offscreen with Qt's software renderer (see [Testing](testing.md)). The fixture
`ui` is a window with a fake systemctl, a fake sound server and the configuration of `tests/support/gui.py`;
`make_ui(**dependencies)` makes one with others. `tests/support/quick.py` (`Ui`) finds items by their `objectName`
(`rail_slots`, `page_channels`, `card_3`, `row_<key>`), clicks them, types into them and presses keys. A test of a
backend that needs no window builds the backend alone.
