# Audio

How the daemon reads the sound server and measures the meters (`audio/`).

## The meters

- **Passive, native captures.** The meters use `pw-record` with `node.passive = true`: a capture never wakes a
  device, never lights the microphone indicator, and never switches Bluetooth headphones into headset mode.
- **Native PipeWire streams on purpose.** WirePlumber 0.5.18 (PipeWire 1.6.10) restores captures of PulseAudio clients
  (`parec`, peak detection streams) at 0 % volume, so those would only get silence.
  - `state.restore-props = false` keeps WirePlumber from saving the captures at all.
  - `node.dont-reconnect = true` keeps a capture with its device or stream. WirePlumber makes a stream whose target
    is the default when it is linked follow the default (like PulseAudio), so without it the meter of the default
    output would show the next default output after Select.
- **Unbuffered.** `pw-record` runs under `stdbuf -o0` (coreutils). Buffered, its output comes in blocks of 4096 bytes
  (64 ms at 8 kHz), so the meters lagged and two meters of the same audio differed by up to that much. Unbuffered, it
  writes every cycle of the graph; the daemon takes the peak of every 20 ms.
- **Stall restart.** WirePlumber links a passive capture only once and gives up when that fails, e.g. while Bluetooth
  headphones disappear and streams move. A capture that gets no audio for 3 s while its device or stream plays is
  started again.

## Meter points from the volume

Measured with PipeWire 1.6.10: a tone into a null sink, the volume and Mute of the test stream and sink set with
`pw-cli set-param`.

- A playback stream and an input apply their volume and Mute in their own node (audioconvert's channel mixer), before
  their output ports, so every capture of them is after both.
- audioconvert has monitor ports only on nodes with input ports (outputs, capture streams), not on playback streams or
  inputs, so there is no tap before the volume. `node.passive` changes only the scheduling.
- The monitor of an output is before its volume and Mute (`monitorVolumes` and `monitorMute` stay untouched unless
  `monitor.channel-volumes` is on).
- pipewire-pulse turns a PulseAudio volume v into the linear channel volume v³ (50 % is 0.125).

So the meters capture what they can and scale it with the volume the sound server tells (`meter.scale_of()`):

- **pre-fader** divides the audio of a stream or input by v³. The audio of a muted stream or input is gone, and its
  pre-fader level with it.
- **post-fader** multiplies the monitor of an output by v³ (0 while muted).
- The volume news is ahead of the captured audio, so after a change the division uses the loudest of the volumes of
  the last 0.3 s (`GAIN_SETTLE`): a fader pulled down must not light the clip LED.

Reference: `spa/plugins/audioconvert/audioconvert.c` (monitor ports in `reconfigure_mode()` only for
`SPA_DIRECTION_INPUT`; the monitor volume in `impl_node_process()`).
