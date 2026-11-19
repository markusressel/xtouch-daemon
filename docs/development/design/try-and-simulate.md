# Design: try changes and situations on the device

Status: built (2026-11-18), extended by [the virtual twin](virtual-twin.md). To be replaced by
[Previews, on the device or only in the GUI](previews.md) (proposed 2026-11-19).

## Problem

The GUI has two ways to see a configuration before it is real, and they don't know each other:

- **Try on the device** (the live preview, `live.StartPreview`): the daemon runs the unsaved configuration of the
  editor instead of the file. The device follows every edit, but only in the situation there is right now.
- **Simulate** on the page Slots: what the slots would show in another situation (another mode, states on or off,
  channels absent, so many people in the call, applications that play, devices without a channel). The resolver
  computes it in the GUI, only the drawing shows it, and nothing can be played: no daemon runs those strips.

Both answer "what would the device do if ...": with this configuration, and in this situation. Trying a situation on
the device itself (the real one, or the virtual one) is what Simulate can't do.

## Idea

One preview with two optional parts, both run by the daemon:

- **the configuration**: the editor's (unsaved changes), or the file;
- **the situation**: the what-if of Simulate, or the real one.

The switch "Try on the device" (next to Save and apply) sends whatever differs from reality: the unsaved changes,
and while Simulate is open, its situation too. With the switch off, Simulate stays what it was before: the drawing
only. So the real device never changes without that switch (decision 1).

## The situation in the daemon

`StartPreview` gets an optional `situation` (`slots.outcomes.Situation`: `mode`, `on`, `flipped`, `people`, `apps`, `devices`,
as `gui.domain.simulate.WhatIf`), and its `config` may be None: the file's configuration, in that situation.

The `SlotEngine` runs a situation in a second `Simulation` of its own (`what_if`), next to the real one:

- **States and the mode** are overrides and the mode picked of that `Simulation`: each state of the scene is forced
  `on` or `off` as the situation says, the mode is picked. The real overrides and the mode picked are not touched.
- **Presence and the members** come from an `Observation` made for the situation (`Situation.observation`):
  for a present `apps` channel an application its `match` takes, for an `output`/`input` channel its devices, for a
  `person` channel that person in the call; absent ones get none. The pools get their stand-ins: `apps` applications,
  `people` people, `devices` devices. Stand-ins are taken from what is real first (applications that play now,
  people in the call, devices without a channel), then made up (`App 3`, `Person 2`, `Device 1`): a real one has
  audio behind its strip, a made-up one shows its label on a strip that controls nothing.
- **Delays and dwells** apply as in reality: a state switched on in the situation waits its `delay_on`, a channel
  that goes absent stays `absent_after` seconds. That is the point of trying it on the device.
- The real `Simulation` is not stepped while a situation runs, and nothing of the situation is kept: no
  `slots.json`, no `people.json`.

`engine.active` is the `Simulation` that runs (the situation's, or the real one); the `SlotMixer` and the live view
use it (see [Live view](../architecture/live-view.md#live-preview) for the preview around it). Home Assistant keeps the real one: its slot sensors and state sensors are not updated while a situation runs,
so automations never see a made-up situation. The live view tells `simulated: true` in the snapshot, with the slots
and states of the situation.

What the device does on its own during a situation: the chord, Home Assistant's mode select and the overrides go to
the real engine (they are real requests); the device shows the situation until it ends.

The situation ends with the preview: the switch off, Simulate ended (the configuration stays previewed if it has
changes), the window closed or not answering for `PREVIEW_TIMEOUT`, the file changed. Then the real `Simulation`
steps again at once and the slots show reality.

## The GUI

- **Simulate** with the switch on: the what-if goes to the daemon (debounced like edits), the drawing shows the live
  device (with the accent frame while the situation runs), the cards show the daemon's slots and their why, and Play
  works: the faders of real stand-ins move their audio.
- **Simulate** with the switch off: as before, the resolver in the GUI, the drawing only, no Play. Its bar says
  "Only in the drawing: turn on Try on the device to run it on the device."
- **The switch** is there while there are unsaved changes or Simulate is open, and a daemon can take it.
- **The pill** next to it: "On the device, not saved", "On the device · simulated", "On the device, not saved ·
  simulated", "Sending to the device…", "Paused: problems".
- **Esc** ends Simulate as before; with the switch on the device goes back to the real situation.

## Decisions (2026-11-18)

1. Simulate drives the device only while "Try on the device" is on. Without it, nothing reaches the device.
2. One preview in the daemon (configuration and situation), not a second mechanism: the same client, heartbeat,
   timeout, and ending.
3. Stand-ins are real where they can be, made up otherwise.
4. Home Assistant never sees a situation.

## Not now

- The chord and Home Assistant changing the situation instead of reality while one runs.
- A banner on the device ("SIM") while a situation runs.
