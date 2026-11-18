# History: strips that move

Status: built on the old format, then replaced by [channels, states and slots](../design/slots/index.md) before 0.1.0.
Its other half, one strip switching between outputs, stays: [Design: output choices](../design/choices.md).

## Collapsing strips

`collapse = true` on a strip: while it had nothing to control (no device, no stream, no participant) for
`behavior.collapse_hold` seconds, it gave up its fader and the strips after it moved left. A file could list up to 32
strips; the first 8 present ones got the faders, the rest waited. Placement waited while a finger was on the device,
and each change was logged ("Strips: Buds appears at 2, Browser moves to 3, Spotify waits").

It went because the fader under the finger changed with things far away from it, which hurts muscle memory. Now a
channel keeps its slot (`"buds if present"` above `auto`), and a pool of channels fills by its order for those who
want moving strips.

## `inherit` from any layout and strip

`type = "inherit"` with `layout` and `strip` (a position or an `id`) took another layout's strip, with chains
resolved and loops an error. State was not shared across layouts: a layout switch built new controllers. It went with
the layouts; a channel now is the same one wherever it shows.
