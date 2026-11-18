# Design: output choices and strips that move

Status: implemented on `feature/dynamic-strips`; see [Decisions and deviations](#decisions-and-deviations) at the end.

Two features:

1. **Choices (A):** one strip switches between several outputs (or inputs), each optionally in its own sound card
   profile. For example Phones (analog), Speaker (digital) and Buds (Bluetooth), cycled with Select.
2. **Collapsing strips (B):** a strip that has nothing to control gives up its fader, and the strips after it move
   left to fill the gap. A configuration can list more than 8 strips; the first 8 that are present get the faders.

They are independent, but they compose: a strip with choices is absent when none of its choices is there.

## Motivation

The author's setup has three outputs: analog headphones and a digital speaker on one sound card (two profiles), and
Bluetooth headphones that come and go. Only one is used at a time. Today this takes two or three strips, or one
strip where Select switches the device and Rec switches the card profile. That second way is two buttons, and Rec
does nothing while the Bluetooth device is shown.

When the Bluetooth headphones are off, their strip is dead: a fader for nothing. The strips after it (Browser, ...)
should move up and use it.

---

## A. Choices

### Configuration

A new option `choices` on `output` and `input` strips: a list of tables.

```toml
[[strip]]
type = "output"
color = "cyan"

[[strip.choices]]
label = "Phones"
device = "alsa_output.pci-0000_11_00.4.analog-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:analog-stereo+input:analog-stereo"

[[strip.choices]]
label = "Speaker"
device = "alsa_output.pci-0000_11_00.4.iec958-stereo"
card = "alsa_card.pci-0000_11_00.4"
profile = "output:iec958-stereo+input:analog-stereo"
max_volume = 200

[[strip.choices]]
label = "Buds"
device = "bluez_output.*"
```

(The first draft wrote the choices as inline tables over several lines; TOML 1.0, which `tomllib` reads, does not
allow line breaks in an inline table. See below.)

The keys of a choice:

| Key | Required | Meaning |
|---|---|---|
| `device` | yes | The node name or description, `*`/`?` wildcards allowed (like `device` today). With a wildcard, the first matching device. |
| `label` | no | The top line of the LCD while this choice is active. By default, the start of the device's description, as today. |
| `card` | with `profile` | The sound card (name or description, wildcards allowed) whose profile has to be set for this choice. |
| `profile` | no | The card profile (name or description) the choice needs. Without it, the choice uses the device as it is. |
| `min_volume`, `max_volume` | no | The volume range while this choice is active, like on profiles today. |

Validation (pydantic, with clear messages, as `check-config` shows them):
- `choices` needs at least 2 entries.
- `choices` excludes `device` and `profiles` on the same strip ("use either `choices` or `device`/`profiles`").
- `profile` needs `card`, and `card` needs `profile`.
- `select = false` with `choices` is an error: Select is how one switches.
- Labels are optional; duplicates are allowed but get a warning-level problem in the GUI, if the GUI has warnings (check).

Keep `device` and `profiles` working unchanged. `choices` is the new way for the switching case, and docs point to it.
No migration of existing files.

### Behavior

- **Available:** a choice is available when its device exists. A choice with `card`/`profile` is also available when
  the card exists and has that profile (its device appears only after the switch).
- **Active:** the strip shows the active choice: the one whose device is the default (for `output`, the default
  output; for `input`, the default input). If none is the default, it shows the one shown last, if it is still
  available, else the first available one.
- **Select press:** goes to the next available choice after the active one, wrapping around. It:
  1. switches the card to the choice's `profile` first, if the choice has one and the card is not in it. Reuse the
     `_Switch` mechanism of `strips/device.py`: the label shows at once, the device is awaited, and on failure the
     strip goes back.
  2. then makes the choice's device the default.
  A press while a switch is still pending goes on from the pending target, so fast presses step through the choices.
- **Select LED:** on while the active choice's device is the default (same meaning as today).
- **Rec:** keeps its normal `rec` indicator meaning (`recording` etc.). It is no longer used for profiles on this strip.
- **Label:** the choice's `label`, else the description start (as today).
- **Volume range:** the choice's `min_volume`/`max_volume`, else the strip's, else `[behavior]`.
- **Fader/mute/encoder:** act on the active choice's device, as they do on a device strip today.
- **Nothing available:** the strip behaves like a device strip whose device is missing (as today). With B, it is
  *absent* (see below).
- **Moved elsewhere:** if the default changes elsewhere (pavucontrol, a Bluetooth connect where WirePlumber makes
  the headphones the default), the strip follows it when the new default is one of its choices.
- **Two choices on the same card in the same profile:** both are available, and switching between them only changes
  the default.

### Home Assistant

The existing entities of output strips keep working. Add a `select` entity for a strip with choices
(`select.<ns>_<id>_output`), with the labels as options: choosing one in Home Assistant switches like Select does.
Follow how the layouts branch registers its `select.<ns>_layout` entity.

### CLI

- `xtouch-daemon list-devices` must show cards and their profiles (name and description), so `card` and `profile`
  can be filled in. Check what it shows today, and add what's missing.
- `check-config` describes a choices strip ("output: Phones, Speaker or Buds (Select switches)").

### GUI

- A table editor for `choices` on output/input strips. Columns: label, device, card, profile, min/max volume. Use
  the existing `Tables` field of `fields.py`.
- Pickers come from the sound server state the GUI already reads: devices for `device`, cards for `card`, the
  profiles of the chosen card for `profile`.
- `device`/`profiles` and `choices` exclude each other. The GUI shows the one in use; switching between them keeps
  the other's values, like the kept-options feature does for strip types.
- Explanations and doc links, like the other options (`gui/domain/docs.py`, the meanings in `config.py`).
- The device preview shows the active choice's label. Offline (no live view), it shows the first choice.

---

## B. Collapsing strips

### Configuration

A new option on every strip type except `empty` and `homeassistant`:

```toml
[[strip]]
type = "output"
device = "bluez_output.*"
label = "Buds"
collapse = true          # gives its fader to the strips after it while no Bluetooth headphones are there
```

And in `[behavior]`:

```toml
[behavior]
collapse_hold = 3        # seconds a strip stays after it became absent, before the strips after it move
```

- `collapse` (bool, default `false`).
- `collapse_hold` (seconds, default 3, ≥ 0).
- **More than 8 strips:** allowed, up to a sane maximum (32). Validation fails if there are more than 8 strips and
  fewer than `count - 8` of them have `collapse = true`, since some strips could then never get a fader. The message
  says which strips can never show.
- **`homeassistant` strips** can't collapse: their entities are always there, and automations rely on them.
- **`empty`** can't collapse either: it exists to reserve a place.

### When a strip is absent

| Type | Absent while |
|---|---|
| `output`, `input` | none of its devices (`device` patterns, or the available `choices`) exists. With `device` unset (the default device), never. |
| `apps` | none of its applications has a stream (playing or paused). |
| `auto` | it has no application assigned (after `auto_hold`). |
| `voip` (layouts) | the provider reports no participant for it. |
| `inherit` (layouts) | its resolved strip is absent. |

A strip becomes absent only after it has been absent for `collapse_hold` seconds. It becomes present again at once.
Both changes are debounced per update: one placement per audio state update.

### Placement

The strips are a **flow**, in config order (after layout resolution, see below). The physical strips 1..8 show the
first 8 strips that are present or don't collapse. Remaining physical strips (fewer than 8 present) show nothing:
dark, faders down, like an `empty` strip. Strips beyond those 8 wait off the device.

Example (the author's case):

```
config:  Out(choices)  Buds(collapse)  Browser  Games  VoIP  auto  auto  Mic  Spotify(collapse, apps)
no Buds: Out           Browser         Games    VoIP   auto  auto  Mic   Spotify
Buds on: Out           Buds            Browser  Games  VoIP  auto  auto  Mic       (Spotify waits)
```

Rules:
- **Identity:** a strip's state (controller, held auto app, pending switches, volumes, meters) belongs to its config
  entry, not to the physical strip. Moving a strip moves its controller to another physical strip: LCD, LEDs,
  ring and fader (the motor glides to the controller's value) follow.
- **Don't move under a finger:** while any fader is touched, or any button is held, placement changes wait (up to
  the release). Check how the layouts branch defers a layout switch, and reuse that.
- **Home Assistant ids:** the default `strip_<position>` id of a strip is its **config** position (1-based in the
  layout's list), not the physical one. Today the two are the same, so nothing changes for existing setups. Document
  this.
- **The meter capture** follows the controller (the capture targets are a function of the controllers on the device).
- **Logging:** each placement change at info level: "Strips: Buds appears at 2, Browser moves to 3, Spotify waits".

### Interaction with layouts

Each layout is a strip list, a flow. `inherit` resolves first. Then the flow places the resolved list. A layout
switch places from scratch (no hold). Per-layout placement is independent: collapsed state is computed from
the current audio state, so no state is carried between layouts beyond the per-entry hold timers of the default
layout's strips. If that is complex, a switch may simply reset the hold timers.

### Live protocol and GUI

- **Snapshot:** add the assignment, e.g. `placement: tuple[int | None, ...]`. For each physical strip, the index of
  the config strip it shows, or None. It is optional and versioned, like the other later fields, so an older GUI and
  an older daemon keep working.
- **Device preview in the GUI:** shows the live placement while the daemon tells it. Clicking a physical strip
  selects the config strip it shows. Offline: the static placement with every strip present.
- **Editor:** every config strip has to be reachable, including those beyond 8 and the collapsed ones. Add a compact
  strip list or overflow row (the implementer picks; follow docs/development/architecture.md's GUI section once the GUI
  architecture rework has landed). It shows which strips are on the device now, which are collapsed, and which wait.
- **Option order:** `collapse` goes with the strip-level options (the GUI agent is making the order follow the
  device; put it near the top, after the type-specific "what it controls" fields).
- "Add strip" works beyond 8 only when that stays valid (see validation), otherwise it explains why not.

### Docs

- A page `docs/configuration/collapsing.md` (or a section in strips.md), with the example above.
- A clear note: **moving strips are bad for muscle memory.** The fader under your finger may control something else
  than a minute ago. The feature is opt-in for that reason. The LCD labels say what each strip is.
- Devices docs: `choices`, with the Phones/Speaker/Buds example, and how to find `card` and `profile`
  (`list-devices`).
- `check-config` output, the GUI page, CHANGELOG, `config.example.toml` (commented examples).

---

## C. `inherit` from any layout and strip

Added later, at the user's request. Today an `inherit` strip takes the strip of the default layout at its place.
It can name another layout and another strip:

```toml
[[layout.strip]]
type = "inherit"
layout = "voice"   # optional, by default the default layout (as today)
strip = 3          # optional: a 1-based position in that layout's list, or a strip `id` string; by default the same place
```

- **Validation:** an unknown layout or strip is an error, and so is a strip `id` that more than one strip of that
  layout has. Chains (an `inherit` of an `inherit`) resolve, up to a limit; a loop is an error that names the
  cycle.
- **`voip` with `count` > 1:** decide and document. (Later moot: `count` is gone, see the decisions.)
- **Resolution before the flow (B):** a referenced strip that collapses collapses here too. It carries all its
  options along, also `launch`.
- **State:** the state of a strip that several layouts share (the held application of an `auto` strip, a pending
  switch) is shared: the same entry is the same controller, so a layout switch does not lose it. If that is hard
  given how layouts build controllers, decide and document.
- **Home Assistant:** a referenced `homeassistant` strip keeps the entity ids of its source (its `id` or its
  position there), and its entities are not registered twice.
- `check-config`, the GUI (pickers for layout and strip on `inherit` strips; the preview shows the referenced strip),
  docs (`layouts.md`), CHANGELOG, tests.

## Implementation notes

- **Config:** `config.py`. Choices are a `ChoiceConfig` model. `collapse` goes on `_StripConfig` (with validators
  that refuse it on `homeassistant`/`empty`). Raise the strip count limit with the collapse validation. Keep
  `config.py`'s field order for the TOML/comment output sensible; the GUI's order is its own (explicit order in the
  GUI schema).
- **Strips:** `strips/device.py` gets the choices logic (maybe a `ChoicesController` next to `DeviceController`,
  sharing the profile-switch code). Each controller type gets `absent(state) -> bool`.
- **Placement:** a pure function `place(strips, present, held) -> tuple[int | None, ...]`, fully unit-tested. A small
  owner (in the mixer, or wherever layouts switch strips) applies changes: rebinds controllers to surface strips and
  defers during touches. Hardware interactions timed or racing must be in a strictly typed state, not loose dicts.
- **Tests:** fake backend scenarios.
  - A Bluetooth device appears: Buds shows at 2, Browser moves to 3, the faders glide.
  - It disappears: after `collapse_hold` the strips move back, not before.
  - A touched fader defers the move, which happens on release.
  - Choices cycle through all three, the profile switch then the default, and a failed switch reverts.
  - A pending switch plus a second press goes to the next one.
  - HA select switches the choice.
  - Snapshot placement round trip; the GUI preview shows the placement.
  - Validation messages.
  - Coverage stays at 100 % (AGENTS.md).
- **Docs build** strict. `just lint`, pyright 0 errors.

## Later

- `pin = true`: a strip that keeps its physical position while others flow around it.
- A layout rule on device presence (`devices = ["bluez_output.*"]`), as an alternative to collapsing.

---

## Decisions and deviations

What the implementation decided where this document was open, wrong, or contradicted the code.

- **TOML:** inline tables can't span lines in TOML 1.0 (`tomllib`), so the example of the first draft did not parse.
  The docs use `[[strip.choices]]` tables; a one-line inline table per choice works as well.
- **Select on a choice that is shown but not the default** makes it the default first instead of skipping to the
  next one, like Select on a `device` strip. Otherwise the LED would be off and the first press would leave the
  choice shown.
- **A finished default switch** ends the pending switch when the command returns, not only when the state shows the
  new default: a default that the sound server never reports (another program changes it right back) must not pin
  the strip to the choice.
- **`card` takes a description too:** the `Card` model got its description (`device.description` of the card), which
  `list-devices` now shows next to the name. The profiles were already listed with name and description.
- **Home Assistant select:** its options are the titles of the choices (`label`, else `device`); a second choice of
  the same title gets a number (`Out 2`), since the options of a select must differ. The entity is created with
  `[mqtt]` only and its id is `<id>_output` or `<id>_input` after the strip type. It joins the duplicate-id check
  (`Config.entity_strips()`), not `home_assistant_strips()`, so a strip with choices does not need `[mqtt]`.
- **Duplicate labels** are allowed and get no warning: the GUI has no warning level yet (only errors).
- **Validation of strips that can never show:** the rule "fewer than `count - 8` strips with `collapse`" lets
  e.g. 8 steady strips followed by a collapsing one through, which could never show. The check is per strip: a
  strip with 8 steady strips before it never gets a fader. The message names those strips. The limit is 32 places
  (`voip` counted `count` until it was removed). An `inherit` strip beyond the strips of the default layout is an
  error too.
- **Collapsed stays collapsed:** a strip that collapsed stays so until it is present again, also when it collapsed
  without a hold (from scratch). Each strip has one typed record (`placement._Absence`).
- **Deferring under a finger:** layouts don't defer their switches (they switch at once), so there was nothing to
  reuse. The mixer follows the touches, held buttons and encoder pushes from the device's events and the surface's
  `held` faders, and `Flow` waits while any is there; the release places what waited. The meter tick (every 0.1 s)
  places a hold time that ended without a new state.
- **Without a sound server** nothing moves (the absences are unknown); the first state places from scratch.
- **Layout switches and reloads reset the hold timers:** a new mixer places from scratch, as the document allowed.
- **Snapshot versioning:** the live view never bumps `VERSION` for new fields; later fields are optional with a
  default (`mqtt_state`, `layout`, ...). `placement` is the same: `None` from an older daemon. It holds indexes of
  `Config.all_strips(layout)`: the TOML list, with `inherit` resolved and `auto` strips up to 8. (While a `voip`
  strip had `count` places, these were places, and `Config.places()` mapped them to the list; both went with
  `count`.)
- **`absent` of `apps` strips** looks at streams only: a paused media player (MPRIS) without a stream does not keep
  a collapsing strip.
- **`auto` strips beyond the device** take applications too (the assigner fills slots in config order), so an
  application may go to a waiting `auto` strip when all on the device are taken.
- **`voip` strips** collapse one by one, so with `collapse` an empty call takes no faders and the strips of the group
  that a small one leaves over give theirs up. (First each place of a `voip` strip with `count`; since `count` is
  gone, each `voip` strip, see [Design: layouts](layouts.md#voip-strips-the-group-and-fixed-people).)
- **C, `voip` strips:** decided first: `strip = N` named an entry of the list, so a `voip` strip with `count` came
  with all its places, and an `inherit` without `strip` took one of them. Superseded: every `voip` strip is one strip
  now, so there is nothing special. An inherited `voip` strip is one of the `voip` strips of the layout it lands in:
  with `person` a fixed strip there, without it a strip of that layout's group.
- **C, the same place:** "the same place" is the position in the list, also for another `layout`. Positions after
  the strips of that layout are `auto` strips up to 8; beyond that it is an error.
- **C, state is not shared across layouts:** a layout switch builds a new mixer with new controllers (as reloads
  do); keeping some controllers alive across mixers would mean moving them between `VirtualStrip`s, flows and the
  auto assigner, and inherited strips never kept their state before either. So an `auto` strip takes the
  application that plays at the switch (usually the same one), and a pending choice switch is cancelled with the
  old strip (`StripController.close()`), maybe after the profile switched; the new strip shows the default device
  as it is then. Documented in `layouts.md`.
- **C, Home Assistant ids:** a strip without `id` that lands on another place than its own gets the id of its own
  place (`strip_<n>`), so a referenced `homeassistant` strip, fader or choices select keeps its entities. The ids of
  all layouts are one set, so they are registered once. The same strip twice in one layout is the existing
  duplicate-id error.
- **C, top-level `inherit`:** allowed when it names a `layout` or `strip` (a bare one would refer to itself).
- **C, errors are of the whole file:** like the other layout checks they are model errors, so the GUI lists them in
  the problems, not next to the strip; the preview shows such a strip as "?".
- **C, GUI preview by position:** the GUI resolves `inherit` by list position, like the daemon. (While `voip` strips
  had `count`, the daemon went by places, and the two differed after such a strip.)
