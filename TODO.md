# TODO

## `xtouch-daemon test`: the device answers its inputs

After the sweep `xtouch-daemon test` only logs what happens on the device, which stays dark, and it needs the daemon
stopped. Extend it: after the sweep every strip answers its own controls, so each output of the device and each of
its values can be shown by hand. The meter follows the fader, the buttons step their LEDs through off, on and
flashing, the encoder steps the ring position, the ring mode, the LCD color and the motor fader, and the LCD names
the strip and the last input. The daemon can run the same test, started from the GUI (a button next to Play and Try)
or by the command, so the GUI draws its twin of the device next to it. Design:
[`docs/development/design/interactive-test.md`](docs/development/design/interactive-test.md).

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

## Startup Sequence

I like the startup sequience we have, especially the show, but can we make it even fancier by:
- letting a single wave go from left to right, over the eight faders, in sync with the lighting above them?
- let the leds on the encoder not only turn on but also turn off in a sequence
- let the meter go up and down, and the buttons light up and turn off in a sequence from top to bottom

Also: The GUI still shows something, even if no virtual device is started. I thought we removed that? 
We want the virtual device to be able to show the startup sequence (works already) and also the shutdown sequence (doesn't work currently).
So the user can see that when a device disconnects, its faders return to 0 (do they actually do that, or do they return to 0 on reconnect?).