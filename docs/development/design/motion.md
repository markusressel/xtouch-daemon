# Design: motion in the GUI

Status: built (2026-11-28), with the window in Qt Quick. The technique of the earlier Qt Widgets window is in
[History: motion in the Qt Widgets GUI](../history/motion-widgets.md).

## Problem

Most of the window changes at once: a pill turns from gray to green, a page replaces another, a row above the cards
appears and the cards jump down. The eye loses what changed. Android's Compose animates such changes with a line each
(`animateColorAsState`, `Crossfade`, `AnimatedVisibility`, `animateContentSize`). Qt Quick can do the same, because it
animates the values of items, not pictures of them.

## Decisions

- **The tokens are in `Theme`.** `Theme.fade` (150 ms) and `Theme.resize` (200 ms) are the only durations. QML never
  writes a duration as a literal. One switch, `Motion.enabled` (property `Theme.motion`), sets both to 0, so every
  change happens at once.
- **A `Behavior` animates a value.** A color, an opacity or a size that changes is `Behavior on x { ... }` with a
  `ColorAnimation` or `NumberAnimation` of `Theme.fade`. A pill or a button that changes its tone fades its color
  without any code of its own.
- **`Reveal` instead of `visible`** where a row comes and goes (`XTouch.Controls`, `Reveal.qml`). Its content grows
  from no height to its own height and fades in, or shrinks away and fades out. The items under it move along, as
  with `AnimatedVisibility`.
- **`FadeText` fades a text through.** The old text fades out, then the new one fades in, so two texts are never on
  top of each other. Its width moves to the new text. Use it where a text changes while the user looks at it.
- **A list fades only the rows that change.** A list whose rows change is a `KeyedListModel` (`quick/models.py`). A
  row has a key that stays the same while the row is the same thing (for a slot card: the candidate, where it stands
  against the one shown, why it did not win). A delegate whose key stays animates to its new values; only a row that
  is new comes in, and only a row that is gone goes out. A change of the configuration, such as a name or a color,
  makes every row anew.
- **Pages fade.** The pages of the window and the parts of a page that swap (the inspector and the overview of the
  page Slots, the forms of the channels) fade from the old part to the new one.
- **A card grows with its content.** A card that gets a line more or less animates its height (`Theme.resize`), and
  what is under it follows.
- **Nothing moves while it isn't shown.** An item that isn't visible changes at once, as does everything while the
  window is minimized.
- **Off in tests and screenshots.** The fixture `no_motion` of `tests/gui/quick/conftest.py` and
  `scripts/screenshot.py` set `Motion.enabled = False`, so a test sees the end of a change at once and does not depend
  on time. The tests of motion turn it on and look at the item while it is between its two values.

## Building blocks

| Block | Use | Like |
|---|---|---|
| `Behavior on <value>` with `Theme.fade` | Any color, opacity or size that changes | `animateColorAsState` |
| `Reveal` | A row that comes and goes in a column | `AnimatedVisibility` |
| `FadeText` | A text that changes | `Crossfade` |
| `KeyedListModel` | A list that changes row by row | `animateItem` |
| `Behavior on implicitHeight` with `Theme.resize` | A card that gets a line more or less | `animateContentSize` |

## Next

- Hover: a fade of the background of every button under the mouse.
- Popovers: fade in when they open.
- The other rows that come and go (the message of the preview, the bar of the file on disk, problems).
