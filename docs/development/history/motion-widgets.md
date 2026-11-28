# History: motion in the Qt Widgets GUI

Replaced on 2026-11-28 by the window in Qt Quick: see [Design: motion in the GUI](../design/motion.md). This page keeps
the technique of the widgets (`gui/qt/motion.py`, removed with the widgets) and why it took pictures. The paths
below are those of the removed code.

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
- **Fade through where texts change.** A crossfade shows the old and the new picture at once: a row whose text
  changes shows both texts on top of each other. Given the color behind the widget (`behind`), `fading` fades
  through instead, as Material's "fade through": the old picture fades out on that color in the first 35 %, then the
  color fades away to the new look.
- **A list fades only the rows that change.** A slot card keeps a key for each row (what makes it: the candidate,
  where it stands against the one shown, why it did not win). `StackList.fill` keeps a row whose key stays as it
  is; a row that changes fades through the card at its place (`Fade(..., at=rect)`), a row that comes fades in, a
  row that goes fades out where it was. A fade over the whole card would blink rows that did not change. A change of
  the configuration (a name, a color) makes every row anew.
- **A fade ends when its widget changes its size**: what it shows moves, and the old picture would show it twice,
  apart. Unless what it shows stays where it was (`through_resize`): the rows of a card grow or shrink at the bottom,
  and the color behind grows with the card.
- **`set_role` fades.** Restyling by a property (`role`, `tone`, `variant`, ...) is how the widgets change their look;
  `set_role` runs in `fading`, so every pill, button and row that changes its tone fades without a change of its own.
  `show_status` fades its text and tone together.
- **Pages fade.** `Stack.show_part` and the pages of the window Configuration fade from the old part to the new one.
- **`reveal(widget, shown)` instead of `setVisible`** where a row comes and goes: it grows from no height to its own
  (or shrinks to none, then hides), and fades in or out while it does. The layout around it moves along, as with
  Compose's `AnimatedVisibility`.
- **Nothing moves while it isn't shown.** A widget that isn't visible changes at once; so does everything while the
  window is minimized or offscreen, and while its updates are off (`setUpdatesEnabled(False)`): its picture would be
  empty, and the fade would blank the widget. Take the picture before the updates go off (`with fading(panel):`
  around them, as Simulate does).
- **Pictures without the window.** `picture_of(widget)` renders the widget and its children on nothing; `grab()`
  would paint the background of the window behind it, a box around a pill with round corners.
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
| `fading(widget, through_resize=True, behind=color)` | Content that changes while it grows or shrinks | `AnimatedContent` |
| `Fade(viewport, picture, at=rect)` | A row of a list that changes, appears or goes | `animateItem` |
| `StackList.grow_to` | A card that gets a line more or less (`Motion.RESIZE`) | `animateContentSize` |

## Where it is used

- Every `set_role` (pills, buttons, rows, fields that change their tone or role) and `show_status`.
- The parts of a `Stack` (the inspector and the overview of the page Slots, the forms of the channels, ...), and the
  pages of the window Configuration.
- Simulate: the states and the what-ifs swap with `reveal`; the note under them too.

Snapshot fades could not reach the feel of Compose: a row whose node turned green faded as a whole, its text blinked, and the rows below jumped while the card grew. That is why the window moved to Qt Quick, which animates values instead of pictures.
