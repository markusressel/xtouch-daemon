# Design: the form of a channel

Status: **step 1 built** (2026-11-19), the rest proposed (see Order). Builds on [Previews of the controls](control-previews.md) and [Output
choices](choices.md).

## Problem

The form of a channel works in a wide window and falls apart in a narrower one (about 900 px for the inspector):

- **Choices** are a line of fields each: label, device, card, profile, min and max volume, three ▾ buttons and ×. The
  line is wider than the card, so the whole card scrolls sideways and the help under every option is cut off. The
  label field shows 5 of the 7 characters the LCD has; the device and card fields show the end of a name.
- **Names** (device, card, profile) are a text field with a completer that opens only after typing, and a ▾ menu
  beside it. Neither says which of the known devices the text matches, and wildcards (`bluez_output.*`) are a guess.
- **Known devices** are only the ones the sound server has now. A device of another profile of the card (the digital
  output while the card is in its analog profile) and a Bluetooth device that is not connected are missing, although
  they are what `choices` are for.
- **Numbers** in tables (`min_volume`, `max_volume`) are text fields.
- **The labels of choices and profiles** go on the LCD, but nothing shows them there: the Display card shows the
  label of the channel only.
- **Remove** is × on lines and a trash can on candidates of the slot cards and in the list.
- **Options that are off by default** read as on/off: `select` and `meter` are switches, `meter_point` an empty
  combo box (unset, it shows nothing instead of the default it takes).
- **What the channel is** shows only in its title ("Output"): what a type does (`STRIP_TYPE_MEANINGS`) shows in the
  Add menu only. Slots says what a slot is at the top of its form; States has the type as buttons in the middle.

## Idea

### 1. The top of the form

Title, id and "Used by" as now, then one sentence of what the type is (`STRIP_TYPE_MEANINGS`), with "Learn more",
like Slots. E.g. "An output device (speakers, headphones): the fader sets its volume. One device, one of several, or
whatever is the default output." The cards below then read in that context: the meter of an output shows what plays
on it. States gets the same: the type and its sentence at the top, the type buttons move there.

### 2. A form that fits

- An option row has its name left of the field (144 px) while the card is wide enough for the name, the field and
  its help (at least 320 px for the field, `option_row.FIELD_WIDTH`); below that, the name goes above the field. Help always wraps, nothing
  in a card is wider than the card.
- A list of tables (`choices`, `profiles`) is a list of **small cards**, one per entry, not a line of fields:

  ```
  ┌──────────────────────────────────────────────────────────┐
  │ ⠿  Phones                                           ✎  🗑 │
  │    Analog Output (Family 17h HD Audio)                   │
  │    needs the card in "Analog Stereo Output"              │
  │    20 – 130 %                                            │
  └──────────────────────────────────────────────────────────┘
  ```

  The label (the default label when there is none), the device by its description, what the choice needs and its
  volume range, each line only when it says something. ⠿ drags to reorder (Ctrl+Up/Down too): the order is the order Select goes through. ✎ or a double
  click opens the entry in place as a small form, the same option rows as the rest of the form: Label (as wide as
  its 7 characters), Device, "Switch the sound card first" (card and profile, folded while
  unset), Volume (from, to). One entry is open at a time; Esc or a click outside closes it.
- **Numbers** are spin boxes with their unit ("130 %"), empty while unset with the value they take as placeholder
  ("by default 130 %"); ⟲ unsets them, as on the other options.
- **The Display card** steps through the labels the LCD shows: the channel's, then one step per choice or profile
  ("Select picked Phones", "Rec picked Digital"), following every key in the form.
- **Unset options** show what they take, from where: "Before the fader (the default of `[behavior]`)". For
  `meter_point` that is the empty combo box now.
- **Remove** is the trash can wherever an entry goes (lines, entries, sources, aliases, candidates). × stays on chips,
  where it takes a word out of a field.

### 3. A field for names

One field for every option that names something the sound server or the voice chat has (`device`, `card`,
`profile`, `match`, `ignore`, `person`, the aliases), replacing the text field, its completer and its ▾ menu:

- A click or focus opens the list of what is known; typing filters it (by any part of the name or the description,
  any case) and keeps it open. Up/Down and Enter pick; Esc closes it and keeps the text.
- Each entry has two lines: the description, and the name in monospace, with the parts that match the text
  highlighted in both, and a tag of where it is known from: "default", "now", "profile Digital Stereo",
  "seen 3 days ago". Presets come first, under their heading, as in the menus now.
- Under the field, while the text is set: what it matches, with the matches highlighted. "Matches Speaker
  (Digital Stereo), not there now" or, for `bluez_output.*`, "Matches 2: WH-1000XM4, Buds Pro (the first one that is
  there)". "Matches nothing known" in the color of a warning (not an error: a device can come later).
- Picking a device in a choice that is only known with another profile of its card fills `card` and `profile` too.

### 4. Known devices

What the field lists, besides what the sound server has now:

- **From the profiles of the cards**: each profile of a card that is not active has devices it would make. PipeWire
  names them from the card and the profile (`alsa_card.pci-0000_11_00.4` with `output:iec958-stereo` gives
  `alsa_output.pci-0000_11_00.4.iec958-stereo`), for ALSA cards with the usual profiles; UCM profiles (`HiFi`) and
  pro audio name them differently, and get no entry. Tagged "profile <description>": nothing is stored, it is known
  as soon as the card is.
- **Remembered**: the daemon keeps every device it saw in its state directory (name, description, direction, card,
  the active profile, when last seen), and sends the list to the GUI with the snapshot. Bluetooth headphones that are
  off, a USB headset that is unplugged, the digital output after it was used once. Tagged "seen <when>". A device
  not seen for 90 days is forgotten; the list has "Forget" on each remembered entry.

### 5. The buttons

Select, Rec and Solo of a channel each get a table: **what a press does**, **what a hold does** (longer than
0.5 s) and **what the LED shows**, with the actions of `[controls]` of the slots (one vocabulary for both):

```toml
[channel.main.select]
press = "default"   # make it the default; when it is, the next one (as now)
hold = "next"       # show and control the next device, the default stays
led = "default"

[channel.main.rec]
press = "profile"   # the next profile (as now with profiles)
led = "recording"
```

| Action | For | Does |
|---|---|---|
| `default` | output, input | Makes the device shown the default; when it is, the next one of `device`/`choices`. |
| `next` | output, input | The strip shows (and controls) the next one, the default stays. |
| `profile` | output, input | The next of `profiles`. |
| `launch` | apps, auto | Starts `launch` (as now). |
| `mute_others` | all audio | While held, the other strips are muted (a solo). |
| `talk` | input | While held, Mute is off (push to talk). |
| `homeassistant`, `cycle_modes`, `mode:<m>`, `toggle:<s>`, `{ launch = [...] }` | all | As in `[controls]`. |
| `off` | all | Nothing. |

The LED takes the indicators of `rec` and `solo` now (`recording`, `playing`, `default`, ...), plus `shown` for
`next`. `select = true`/`false` and `rec = "recording"` (an indicator) keep working as shorthands: the first is
`press = "default"`/`"off"`, the second `led`. The Buttons card becomes a row per button: what a press does, a hold, the LED; its preview
follows the actions.

### 6. The meter

One choice instead of the switch and the combo box: "Level before the fader" (default), "Level after the fader",
"Off", "As in `[behavior]`". The type sentence at the top (1.) says what the level is of. More than that (a peak
hold, a range) only if it turns out to be missing.

## Order

1. Built. GUI only: the top of the form, a form that fits, the list of cards with LCDs (and the Display card stepping
   through the labels of the choices), spin boxes, unset options, trash cans, the meter as one choice (the
   configuration keeps `meter` and `meter_point`).
2. The field for names, with what the sound server has now and the devices of the profiles.
3. Remembered devices (the daemon's state, the snapshot).
4. The buttons (configuration, daemon, GUI): its own design, from 5.

## Decisions (2026-11-19)

1. **Remembered devices are kept by the daemon**: it sees every device, also while no window is open.
2. **A table per button** (`press`, `hold`, `led`); the flat options of now stay as shorthands.
3. **All actions of the table above** in the first version: `default`, `next`, `profile`, those of `[controls]`,
   `talk`, `mute_others`.
4. **The labels of choices and profiles show in the Display card**, a step each; the list of entries has no LCDs.

## Open

- The meter: is "what it shows" (before/after the fader, off) enough, or should it take more (peak hold, range)?
