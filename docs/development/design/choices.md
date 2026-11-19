# Design: output choices

Status: built. How to use it: [Devices](../../configuration/channels/devices.md). First designed with strips that
moved, which went: [History](../history/dynamic-strips.md).

One `output` or `input` channel switches between several devices, each optionally in its own sound card profile:
Phones (analog), Speaker (digital) and Buds (Bluetooth), cycled with Select. Before, that took two or three strips, or
Select for the device and Rec for the profile, which did nothing while the Bluetooth device was shown.

## Configuration

`choices` is a list of tables (`[[channel.out.choices]]`; TOML 1.0 has no inline tables over several lines):

| Key | Required | Meaning |
|---|---|---|
| `device` | yes | The node name or description, `*`/`?` wildcards allowed; with a wildcard, the first device that matches. |
| `label` | no | The top line of the LCD while this choice is active; by default the start of the device's description. |
| `card` | with `profile` | The sound card (name or description, wildcards allowed) whose profile the choice needs. |
| `profile` | no | The card profile (name or description). Without it, the device is used as it is. |
| `min_volume`, `max_volume` | no | The volume range while this choice is active. |

Errors: fewer than 2 choices; `choices` with `device` or `profiles`; `profile` without `card` or the other way round;
`select = false` (Select is how one switches). Labels may repeat.

## Behavior

- **Available**: a choice whose device exists, or whose card exists and has its profile (its device appears only after
  the switch).
- **Active**: the choice whose device is the default of its direction; if none is, the one shown last while it is
  available, else the first available one. A default changed elsewhere (pavucontrol, a Bluetooth connect) is followed
  when it is one of the choices.
- **Select** goes to the next available choice, wrapping around: it switches the card to the choice's profile first
  (the label shows at once, the device is awaited, and a failed switch goes back), then makes the device the default.
  A press while a switch is pending goes on from its target, so fast presses step through the choices. A choice shown
  but not the default is made the default first, like Select on a `device` channel.
- A finished default switch ends the pending switch when the command returns, not only when the state shows the new
  default: a default that the sound server never reports (another program changes it right back) must not pin the
  strip.
- **The Select LED** is on while the active choice's device is the default. Rec keeps its indicator.
- **Label, volume range, fader, Mute, encoder**: of the active choice, else of the channel, else of `[behavior]`.
- **Nothing available**: like a device channel whose device is missing, absent.
- **Home Assistant**: `select.<ns>_<id>_output` (or `_input`) with the titles of the choices (`label`, else `device`);
  a second choice of the same title gets a number (`Out 2`), since the options of a select must differ.
- **`list-devices`** shows the cards with their descriptions and profiles, to fill in `card` and `profile`.
