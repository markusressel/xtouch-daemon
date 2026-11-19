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

## AI support

Is there anything we should add to either the daemon or the GUI to help AI work with them?
Or is it enough that we have a config and documentation up online?
If we can avoid implementing features for AI, that would be best, but if there is something that would add real value to a user, it is worth it.
I was able to edit the config to my liking with AI pretty easily, but maybe there is still something to make it easier for less smart models?

## Startup sequence on the device

The wave of `show` (light and faders together, see `Surface._wave()`) is tested on the virtual device only. On the
device, check:

- how it looks and sounds: `SHOW_FADER_PEAK` (0.6), `SHOW_STEP` (30 ms) and `SHOW_STAGGER` (60 ms) may need tuning;
  do the motors follow the 100 Hz curve smoothly, and do they get to the bottom at shutdown?
- the meter going down: each level is sent, but the device lets meters fall by itself too.
- a disconnect: pull only the USB cable while the device stays on. Do its faders, LCDs and LEDs stay as they were, or
  does it reset them? (`docs/reference/hardware.md`, "Disconnect", says it is not known yet.)
