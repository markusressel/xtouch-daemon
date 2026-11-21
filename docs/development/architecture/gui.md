# GUI

`xtouch-daemon gui` is an optional editor for the configuration file, in the subpackage `gui` and the extra of the same
name, like the GUI of [openhasp-config-manager](https://github.com/markusressel/openhasp-config-manager). The daemon
itself does not import it. How to use it: [GUI](../../guides/gui.md).

## Layers

- **Toolkit-free domain, thin widgets.** `gui/domain` decides everything, `gui/qt` only shows it and passes edits back:
  - `slots_document`: the file as plain values, validated with `parse_config()` (the messages of `check-config`), and
    saved;
  - `slot_stacks`: the stacks of the slots as rows to edit; `simulate` and `slots.outcomes`: what other modes and
    states would show;
  - `looks`: how the live view draws each strip; `status`: whether the device runs the saved file;
  - `sources`: suggestions from the sound server; `problems`: which page shows a problem;
  - `apply()`: reload, restart or "the daemon does not run".
- **One source of truth: the `Editor`** (`qt/editor.py`) holds the document, its history and its validation. Views read
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

- **Pages by what they edit.** A rail (`gui/qt/window/rail.py`) has the pages Slots (a card per slot with its stack,
  an inspector for the candidate picked, why it shows, Simulate), Channels, States and Settings (`[device]`,
  `[behavior]`, `[aliases]`, `[mqtt]` as "Home Assistant", `[voip]`). Slots, Channels and States are two panes with a
  `PaneSplitter` (`gui/qt/window/splitter.py`) that keeps its share in `QSettings`.
- **The device on every page.** The drawing of the device (`DeviceView`, `gui/qt/window/device_view.py`) and the pages
  with their rail are `QDockWidget`s: one above the other at first, at any side, or windows of their own;
  `QMainWindow.saveState()` keeps where they are. The central widget is an empty placeholder, so the docks have all the
  room. The header and the footer are fixed `QToolBar`s, so they reach across the window. A click on a strip of the
  drawing picks its slot on the page Slots. The menus hold what is used now and then (the theme, the zoom) and the
  keys of the window.
- **The log of the daemon.** The window Log (`LogView`, `gui/qt/log_view.py`) is a third dock, hidden at first; it asks
  the daemon for its log over the live view only while it shows (see [Live view](live-view.md#log)). What it keeps,
  filters and searches is in `gui/domain/log.py`.
- **Previews of the controls.** `gui/domain/demos.py` makes a short scene per part of a strip from the values in the
  form; `PartPreview` (`gui/qt/preview/part_view.py`) shows it in a `StripView` cut to the part. See
  [Design: previews of the controls](../design/control-previews.md).
- **Undo instead of questions.** `History` (`gui/domain/history.py`) keeps the states of the document before every
  edit, so removing a channel or reverting the file asks nothing and Ctrl+Z brings it back. Typing into one option is
  one step. Ctrl+Z undoes in the document also while a text field has the focus (`gui/qt/window/input_filter.py`,
  which also keeps the wheel from changing a field under the mouse).

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
- **Nothing pops up.** A popup window (a `QMenu`, the list of a `QComboBox` or a `QCompleter`) grabs the keyboard
  and the mouse, on X11 the whole display, so a screenshot key would do nothing while it is open. Menus stay `QMenu`s
  (their actions keep their shortcuts in the window) but open as popovers: `show_menu`, `attach_menu` and `MenuBar`
  in `gui/qt/fields/menu.py`, with `describe` for an entry that says what it does. Drop-downs are `Choice`, the
  suggestions under a field a `SuggestionList` (`gui/qt/fields/suggestions.py`). The fixture `no_popups` of the GUI
  tests fails a test in which a popup shows.

## Drawing and updating

- **Built once, updated in place.** The pages build their widgets once, and showing the document loads the values
  into them (`OptionRow.load()`); no page is cleared and built again. A part that comes and goes (an absent section,
  the form of each channel type) is a page of a `Stack` sized to its current part, not a widget shown and hidden.
  `Stack.add` puts a part in the window, hidden, as soon as it is built: a new theme reaches it (`refresh_icons`,
  `refresh_help` go through the children of the window), and it goes with the window.
- **Built when first shown.** The page Channels builds the form of a channel type (or a pool) the first time it
  shows, and keeps it: most types never show in a session, and building all of them took most of the start of the
  window. While the page is hidden, the form of the selection waits (`ChannelsPage.pending`) until the page shows or
  someone asks for its rows; the list, with its marks for problems, is up to date all the time.
- **No layout for what stays the same.** Showing the document again, or a live update with every change of the device, changes no
  geometry when nothing differs: `set_text` and the tab texts are set only when they differ, `theme.set_role` restyles
  only for another role, and the list chips stay while their values are the same. Icons are kept with their name and
  color (`theme.set_icon`), so a new theme draws them again (`theme.refresh_icons`) without building a page.
- **One visual system.** `qt/theme/` holds the design tokens: the colors of the dark and the light theme (text at
  4.5:1 or more and the outlines of controls at 3:1 or more on every surface, WCAG 2.2 AA, checked by the tests), a
  4 px spacing scale, radii, the height of controls, a type scale relative to the desktop font, and the colors of the
  device for the drawing, the same in both themes. Widgets set style roles (`theme.set_role`) and take their sizes
  from the tokens instead of styling themselves. The drawing decides what a strip shows (a `StripFace`) apart from
  painting it.

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
  paint, a size hint) while `sys.excepthook` is Python's own. `run_gui` installs `gui/qt/errors.py` first: such an
  error is logged with its traceback, and the window says it in its status line and goes on.
- **Ctrl+C and SIGTERM wait for the event loop.** Python runs a signal handler between any two bytecodes, e.g. in a
  paint or while the window is built. The handler of `run_gui` (`QuitSignals`), installed before anything of Qt, only
  notes the signal; a timer of the event loop closes the windows, which ask about unsaved changes, and not while a
  dialog asks already.

## PyQt6, QtAwesome and qt-themes

The same as openhasp-config-manager, so the tools look and work alike. The wheels carry Qt itself, so
`uv tool install` needs no system packages (GTK 4 through PyGObject needs the system libraries and a compiler); Qt
paints the drawing of the device with `QPainter` and does drag and drop; pytest-qt runs the widgets offscreen.
