# Design: previews of the controls

Status: built (2026-11-17).

## Problem

The form of a channel lists its options, with help under each. What they do on the device has to be imagined: which
LEDs a `rec = "recording"` lights and when, how the ring of a `balance` encoder looks, whether the meter of a
`pre_fader` strip stays up while the fader goes down.

## Idea

The form of a channel (and of the pools `[pool.apps]`, `[pool.people]` and `[pool.auto]`) groups its options by the part of the strip they are about,
in the order of the device from top to bottom, each in a card:

| Group | Options | Preview |
|---|---|---|
| What it controls | `device`, `choices`, `profiles`, `match`, `person`, `launch`, ... | none |
| Encoder | `encoder` | the encoder with its ring |
| Display | `label`, `color`, `talking_color`, `lit_when_idle` | the LCD |
| Buttons | `rec`, `solo`, `select` | Rec, Solo, Mute, Select |
| Fader and meter | `fader`, `min_volume`, `max_volume`, `meter`, `meter_point` | the meter and the fader |
| Slots | `absent_after`, `in_pool`, `tags` | none |

The card of a part has a small drawing of that part on its left: the same drawing as the window Device (a `StripView`,
cut to the part), so it looks exactly like the device. It shows a short scene, a step at a time like pictures (‹ and ›,
with "2 / 4" between them), with a caption under it that says what happens, e.g. for `rec = "recording"`:

1. "Audio plays": Rec dark.
2. "An application records": Rec lit.
3. "Muted": Mute lit.

The scene follows the values in the form at once (also unsaved ones, and the defaults of unset options), and stays at
the step shown, so changing an option shows its effect right there. (A first version played the steps in a loop: too
fast to follow.)

### Scenes

- **Encoder** (`encoder`): `volume` turns the volume up in steps (ring filling, `wrap`), a push goes back to
  `behavior.reset_volume`; `balance` turns from the center to the right (`boost_cut`), a push centers it; `pick` steps
  through applications (`dot`), a push pins one (`wrap`); `media` seeks forward in a track, a push pauses;
  `homeassistant` turns a number.
- **Display**: plays (label, volume), the fader moves (the new volume), muted, nothing to control (dark, or lit with
  `lit_when_idle`). People: there, talks (`talking_color`), away.
- **Buttons**: plays, records, the default device (output and input only), muted, nothing plays. Each LED lights in
  the situations its indicator stands for; Mute in the muted one; Select while the device is the default (`select`).
- **Fader and meter**: the fader at the bottom, at the 0 dB mark (with a range across 100 %) and at the top, with the
  volume of each place (`min_volume`, `max_volume`, `behavior.unity_at`) in the caption; the meter shows a steady
  level before the fader (`pre_fader`), or one that follows it (`post_fader`), and what a mute does to it.

## Parts

- `gui/domain/demos.py` (no Qt): the groups (`GROUPS`), and `scene(part, strip_type, values, behavior)`, the frames
  (`Frame`: a caption and a `StripState`) from the resolved values. Tested without a window.
- `gui/quick/device/part.py` and `qml/XTouch/Device/PartPreview.qml`: a strip cut to a part, with ‹ and › to step through the frames.
- `StripView` takes any `StripHost` (the `Preview` of the window Device, or a `PartView`).
- `ChannelsPage` builds a card per group.

## Not now

- Previews in the inspector of the page Slots (the options of a place). The same groups fit there.
