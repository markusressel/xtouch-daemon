# States and modes

Part of [Design: channels, states and slots](index.md).

A state is a named condition that is on or off, evaluated all the time and visible everywhere: the GUI, the live
view, Home Assistant.

```toml
[state.call]
voice_chat = true           # in a channel of the voice chat, also alone (from the bridge)
recording = ["discord", "vesktop"]   # or: one of these records (they open a capture stream only in a call)
delay_off = 5               # stays 5 s after: a reconnect, not much longer

[state.wireless]
devices = ["bluez_output.*"]

[state.focus]
when = "not call and not gaming"

[state.night]
homeassistant = true        # Home Assistant feeds it: switch.xtouch_state_night_input
```

## Sources

| Source | On while |
|---|---|
| `apps` | One of these applications has a playback stream (playing or paused). Names and presets as `match`. |
| `recording` | One of these applications has a capture stream. Not for Mumble, which keeps its capture open while connected, even alone; use `voice_chat`. |
| `voice_chat` | The voice chat reports that you are in a channel, also alone: joining one says you mean to talk (the mic shows before anyone comes, and the pool `people` covers who comes). |
| `processes` | A process of one of these names runs (polled every 2 s while any state uses it). |
| `devices` | A device (output or input) that matches is there. |
| `channels` | One of these channels is present: ids, or `"#tag"`. |
| `homeassistant` | Its input switch in Home Assistant (`switch.xtouch_state_<id>_input`) is on. |
| `when` | The expression holds. Not with other sources: a state is either composed or has sources. |

- A state with several sources is on while any of them is. Without sources it is only what its override says.
- **Delays**: `delay_on` (default 0) and `delay_off` (default `behavior.state_delay_off`, 3 s; 10 s for modes) apply to
  the sources, not to the override. A composed state has none of its own: its expression has the delays of what it
  names, so `call` and `not call` never overlap.
- References between states and modes must not form a loop; `check-config` names it.

## Overrides

Every state has an override: `auto` (the sources decide), `on` or `off`, set from Home Assistant
(`select.xtouch_state_<id>`), the GUI or a button (the chord, `[controls]`). One rule for all states
and modes:

- `on` and `off` take effect at once, past the delays; back to `auto`, the sources decide at once too.
- An override lasts **until the sources change** (an edge after their delays), then it is `auto` again. Example:
  `gaming` forced off while a game runs (to use the default mode for a moment); when the game exits, `auto` again, and
  the next game brings the mode. So an override set while a `delay_on` is pending ends when the delay does.
- `persist = true` keeps it across edges, until it is set to `auto` by hand. States without sources have no edges, so
  their override is kept by itself.
- Overrides are kept across restarts. The first evaluation after a start is the **baseline**, not an edge: a kept
  override survives it.
- An active override shows: hatched in the GUI's state bar, `override` in Home Assistant's attributes, and in the
  banner on the LCDs when it is set and when the daemon starts.

## Modes

Modes are states with `mode = true`. Exactly one mode is on: the one with the highest `priority` whose sources are
on (then the first in the file), else `default`. A mode has a `label`, the banner across the LCDs.

```toml
[state.gaming]
mode = true
label = "Gaming"
processes = ["@steam-games"]
apps = ["@games"]
```

- The override is one: `select.xtouch_mode` with `auto` and every mode, `xtouch-daemon mode gaming`,
  `mode --next`/`--previous`, `mode auto`. `--next` and the chord cycle through `default` and the modes in the
  order of the file (not through `auto`).
- A picked mode lasts until the rules want another mode than before: edges that don't change what the rules want (a
  mode of lower priority starts) and edges of modes with `persist` don't end it.

## The chord

`[switching] chord = { strips = [1, 8], action = "cycle_modes" }` (the default): the Solo buttons of those strips held
together. `action = "mode:<id>"` picks a mode, `"toggle:<state>"` toggles the override of a state (`auto`, the
opposite of its value now, `auto`). The same actions are those of buttons in [`[controls]`](slots.md#controls); the Solo
buttons of the chord can't be claimed there and don't hold slots.
