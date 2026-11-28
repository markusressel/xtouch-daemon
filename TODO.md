# TODO

## The Game strip starts at 0 %

The strip of the `game` channel starts at 0 % when a game starts, even though its volume was set to something else
before. Two possible causes, not checked yet:

- Ours: gaming builds a new mixer (the prototype of slots), so the strip is new and has forgotten its volume
  (`AppGroupStrip.group_volume`); until the game has a stream the fader is down ("idle"), then it shows the volume
  the stream starts with. Step 5 of the slots (`docs/development/history/slots.md`) keeps one controller per channel
  for as long as the configuration, which fixes this within a run.
- PipeWire's: WirePlumber restores the volume of a stream by its properties (mostly `application.name`). Games under
  Proton/Wine often have a generic or changing name, so nothing is restored.

Next time a game starts: `pactl list sink-inputs` shows its `application.name` and the volume it starts with. If
PipeWire doesn't restore it, remember the volume per game ourselves.

## Startup sequence on the device

The wave of `show` (light and faders together, see `Surface._wave()`) is tested on the virtual device only. On the
device, check:

- how it looks and sounds: `SHOW_FADER_PEAK` (0.6), `SHOW_STEP` (30 ms) and `SHOW_STAGGER` (60 ms) may need tuning;
  do the motors follow the 100 Hz curve smoothly, and do they get to the bottom at shutdown?
- the meter going down: each level is sent, but the device lets meters fall by itself too.
- a disconnect: pull only the USB cable while the device stays on. Do its faders, LCDs and LEDs stay as they were, or
  does it reset them? (`docs/reference/hardware.md`, "Disconnect", says it is not known yet.)


## Bugs

Unused space to the right of the scrollbar on the "Channels" configuration view:
/tmp/screenshots/2026-11-25-10-07-59.png


when I am in the channels tab, and click on slot 2 (Browser)
  for the first time (after app launch), it takes a moment to
  load. A second click loads instantly. When I click on slot
  8 then (Mic), the same thing happens.

  Can we either make that loading faster, or add a loading
  indicator in the meantime? I assume it takes a while because
  it lays out the layout for the first time, which is
  understandable, but still a bad experience.

The hardware item control previews here are awesome, but they look a little harsh, can we round their corners or do something else to make them feel more integrated?
/tmp/screenshots/2026-11-25-10-09-15.png

---

Since we made the "else" entry selectable, we should also have a chip for it here as a last entry:
/tmp/screenshots/2026-11-25-10-17-05.png

Also, deselecting a chip there should deselect the entry in the list as well, right?

And we still have a lot of other inputs where the default value is written in white text instead of gray.
We should create standard components, or a helper or something so this doesn't happen again in the future.
/tmp/screenshots/2026-11-25-10-19-45.png

The "select" button looks (or its text) looks cut off here:
