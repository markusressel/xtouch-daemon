# History: refactoring, November 2026

Status: done (2026-11-18). A pass over the code for structure, without changing what anything does. The steps were
ranked by value against risk; each was one commit, checked with ruff, pyright and the tests that cover it.

## Survey

- 26 000 lines in `src/`. The layers hold: no Qt in `gui/domain`, nothing outside `gui/` imports the GUI, `pyright`
  passes on `src/`.
- The large modules: `gui/qt/window/main_window.py` (1100 lines), `gui/qt/pages/slots.py` (935),
  `slots/model.py` (785), `gui/qt/preview/strip_view.py` (700), `daemon/lifecycle.py` (640).
- `MainWindow` builds the rail, the settings navigation, the menus, the header and the footer, filters the keys and
  the wheel of the whole application, decides which page shows a problem, and runs the service, the file, the zoom
  and "Try without a device".
- `SlotsPanel` holds the widgets of a card (`StackList`, `CandidateRow`, the chips of a rule) next to the page, and
  decides in the widget what belongs to the domain: where a candidate stands against the one shown, which strip type
  the place of a candidate has, and what a pool hands out on a slot.
- Dead code: `demos.AUDIO_TYPES` and `Preview.drop_target` are used nowhere.

## Steps

1. **Dead code.** Remove `demos.AUDIO_TYPES` and `Preview.drop_target`.
2. **Decisions of the page Slots into the domain.** `slot_stacks` gets `row_state()` (a candidate against the one
   shown), `place_strip()` (the strip type of a place) and `member_summary()` (what a pool hands out on a slot and who
   waits). The page calls them; they can be tested without Qt.
3. **The cards of the page Slots in a module of their own.** `gui/qt/pages/slot_cards.py` gets `StackList`,
   `CandidateRow`, the chips and the rule of a candidate, and filling a card. `pages/slots.py` keeps the page: the
   bars, the inspector, Simulate and the edits.
4. **Where a problem is shown, in the domain.** `gui/domain/problems.py` has `place_of(problem)`: the page (and the
   channel, state or slot on it) that shows a problem. `MainWindow.go_to()` only goes there.
5. **The filter of the keys and the wheel.** `gui/qt/window/input_filter.py`: the application-wide filter that keeps
   Undo and Redo from the text fields and the wheel from fields that would change their value. `MainWindow` installs
   it and removes it when it closes.
6. **The rail and the settings in a module of their own.** `gui/qt/window/rail.py`: `Rail` (the pages, their names
   shown or not) and `SettingsPages` (the navigation and the stack of the settings). `MainWindow` keeps
   `rail_buttons` and `nav_buttons` for the tests and `show_page()`.
7. **The geometry of a `Session`.** The conversion between the pixels of the screen and those of the window is one
   function, `scaled()`, instead of written out twice.
8. **The files of the slots.** `daemon/slots.py` keeps the `SlotEngine`; reading and writing `slots.json` and
   `people.json` go to `daemon/slot_files.py`.

After these, the [architecture](../architecture/index.md) names the new modules.

## Left as they are

- **`daemon/lifecycle.py`.** One lifecycle: reload, preview and the run loop share the configuration that runs and the
  mixer. Splitting the preview off would hand the same state around, not make it simpler.
- **`gui/qt/preview/strip_view.py`.** Long, but one thing: painting a strip and the hand on it. Its paint methods
  share the state of the strip and the cached pictures.
- **`slots/model.py`.** The pydantic models of the configuration with their validators; the length is their docstrings,
  which the GUI shows as help.
- **`strips/`.** The controller hierarchy is the extension point of the channel types; it is not duplicated.
- **The live protocol, the configuration format, the MQTT entities and the CLI.** Untouched, as for any refactoring.
- **Tests that fail already.** They are the owner's to fix; a test only gets a moved import.
