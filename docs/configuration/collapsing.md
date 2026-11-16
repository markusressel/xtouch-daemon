# Collapsing strips

A strip with `collapse = true` gives its fader to the strips after it while it has nothing to control, e.g.
Bluetooth headphones that are switched off. The strips after it move one place to the left, and back when it
returns. A configuration may then list more than eight strips: the device shows the first eight that take a place,
the others wait for one.

!!! warning "Moving strips are bad for muscle memory"

    The fader under your finger may control something else than a minute ago. That is why `collapse` is off unless
    you turn it on for a strip. The LCDs always say what each strip is.

```toml
[behavior]
collapse_hold = 3        # seconds a strip stays after it became absent, before the strips after it move

[[strip]]
type = "output"
device = "bluez_output.*"
label = "Buds"
collapse = true          # gives its fader to the strips after it while no Bluetooth headphones are there
```

## When a strip has nothing to control

| `type` | Collapses while |
|---|---|
| `output`, `input` | None of its devices is there (`device`, or the [choices](devices.md#choices) that are there). Without `device` (the default device), never. |
| `apps` | None of its applications has a stream, playing or paused. |
| `auto` | It has no application, after [`auto_hold`](behavior.md#behavior). |
| `voip` | The voice chat has no participant for its place. |
| `inherit` | The strip of the default layout it stands for collapses. |

`homeassistant` and `empty` strips never collapse: Home Assistant's entities are always there and automations rely
on them, and an empty strip is there to keep its place.

A strip collapses after it has had nothing to control for [`collapse_hold`](behavior.md#behavior) seconds (3 by
default), so a device that reconnects or an application between two tracks does not move the strips. It comes back
at once.

## Where the strips go

The strips are a row in the order of the file. The eight strips of the device show the first eight of them that
don't collapse right now; strips of the device that are left over stay dark with their faders down, like `empty`
ones.

An example with nine strips, two of them with `collapse`:

```
file:     Out  Buds(collapse)  Browser  Games  VoIP  auto  auto  Mic  Spotify(collapse)
no Buds:  Out  Browser         Games    VoIP   auto  auto  Mic   Spotify
Buds on:  Out  Buds            Browser  Games  VoIP  auto  auto  Mic           (Spotify waits)
```

- A strip takes everything with it when it moves: its volume, the application of an `auto` strip, a switch that is
  on its way. The LCD, the LEDs and the ring show it on its new place, and the motor fader glides to its volume.
- **Nothing moves under a finger.** While a fader is touched or a button is held, the strips stay where they are;
  they move when you let go.
- The meters capture only for the strips on the device.
- Every move is logged, e.g. `Strips: Buds appears at 2, Browser moves to 3, Spotify waits`.
- Without a connection to the sound server, nothing moves.

There can be at most 32 places (a `voip` strip takes `count`), and every strip must be able to get a fader: a
strip that has eight strips without `collapse` before it never would, which `check-config` reports, e.g.
`strip[9] can never show: 8 strips before them don't collapse`.

## Home Assistant

The default `id` of a strip, `strip_<position>`, is its position in the list of the file (or of its layout), not the
strip of the device it is on. So its entities stay the same when it moves. For strips that are configured where
they are shown, that is the same as before.

## Layouts

Each [layout](layouts.md) is a row of its own: `inherit` strips are resolved first, then the row is placed. A
layout switch places from scratch: a strip that has nothing to control right then collapses at once, without
`collapse_hold`. The same goes for a reload and the start of the daemon.
