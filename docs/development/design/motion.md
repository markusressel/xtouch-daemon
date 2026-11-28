# Design: motion in the GUI

Status: built in parts (2026-11-28): the building blocks, and the first places that use them (below).

## Problem

Most of the window changes at once: a pill turns from gray to green, a page replaces another, a row above the cards
appears and the cards jump down. The eye loses what changed. Android's Compose animates such changes with a line each
(`animateColorAsState`, `Crossfade`, `AnimatedVisibility`, `animateContentSize`); Qt Widgets has nothing of the kind:

- The stylesheet has no transitions. A new `role`, `tone` or `:checked` restyles the widget in the next frame.
- `setVisible` takes a widget out of its layout at once; the layout jumps.
- `QGraphicsOpacityEffect` is one effect per widget (the shadows of the scroll areas use the slot) and slow on large
  widgets.

A rewrite in Qt Quick, which has transitions built in, would cost the whole `gui/qt/` and its tests, the docks and
the forms from the pydantic models: not worth it. Instead, a few building blocks that the widgets call where they
change, so a page needs no animation code of its own.

## Decisions

- **One module, `gui/qt/motion.py`.** Every animation of the GUI goes through it: its durations and easing are the
  tokens of `Motion` (`theme/tokens.py`), and one switch turns them all off.
- **Crossfade, not interpolated colors.** `fading(widget)` grabs what the widget shows (with its children), lets the
  change happen, and lays the old picture over the new one, fading out. It works for any change of the look: a color
  from the stylesheet, a text, an icon, a whole page. No widget paints its own colors for it, so the stylesheet stays
  the one place of the look. Compose's `Crossfade` does the same.
- **`set_role` fades.** Restyling by a property (`role`, `tone`, `variant`, ...) is how the widgets change their look;
  `set_role` runs in `fading`, so every pill, button and row that changes its tone fades without a change of its own.
  `show_status` fades its text and tone together.
- **Pages fade.** `Stack.show_part` and the pages of the window Configuration fade from the old part to the new one.
- **`reveal(widget, shown)` instead of `setVisible`** where a row comes and goes: it grows from no height to its own
  (or shrinks to none, then hides), and fades in or out while it does. The layout around it moves along, as with
  Compose's `AnimatedVisibility`.
- **Nothing moves while it isn't shown.** A widget that isn't visible changes at once; so does everything while the
  window is minimized or offscreen.
- **Off in tests and screenshots.** `Motion.enabled = False` (the fixture `no_motion` of `tests/gui/conftest.py`,
  and `scripts/screenshot.py`) makes every building block change at once, so a test sees the end at once and stays
  independent of time. The tests of `motion.py` turn it on and drive the animations to a time of their choosing
  (`QVariantAnimation.setCurrentTime`), without waiting.
- **Cheap.** A crossfade grabs one picture of the widget and repaints it while it fades (`Motion.FADE`, 150 ms);
  `set_role` with the value it has does nothing, as before.

## Building blocks

| Block | Use | Like |
|---|---|---|
| `fading(widget)` | `with fading(pill): ...` around any change of the look | `Crossfade` |
| `reveal(widget, shown)` | A row that comes and goes in a layout | `AnimatedVisibility` |
| `StackList.grow_to` | A card that gets a line more or less (`Motion.RESIZE`) | `animateContentSize` |

## Where it is used

- Every `set_role` (pills, buttons, rows, fields that change their tone or role) and `show_status`.
- The parts of a `Stack` (the inspector and the overview of the page Slots, the forms of the channels, ...), and the
  pages of the window Configuration.
- Simulate: the states and the what-ifs swap with `reveal`; the note under them too.

## Next

- Hover: Qt applies `:hover` itself, before a widget hears of it; a fade needs the picture before. An event filter on
  the buttons that grabs on `Enter` before the style repaints, or painted hover backgrounds.
- Popovers: fade in when they open.
- The other rows that come and go (the message of the preview, the bar of the file on disk, problems).
