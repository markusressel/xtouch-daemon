# Without an X-Touch

A virtual X-Touch Extender stands in for the real one: use it to follow the [Setup tour](tour.md) before your X-Touch
arrives, or to try a configuration. The daemon treats it like the real one.
[Hardware](../reference/hardware.md#the-virtual-device) lists what is assumed. Use it in the GUI (the easy way) or in
terminals.

## In the GUI

```shell
xtouch-daemon gui
```

While no daemon runs, click "Try without a device" above the drawing of the X-Touch. The GUI starts a daemon with a
virtual X-Touch, which the GUI calls the **virtual device**, and shows it in the drawing. This daemon ends when you
close the window.

The mouse works on the drawing like a hand on the X-Touch (the mode **Play**). See
[GUI](../guides/gui.md#select-and-play).

## In terminals

First start the virtual X-Touch in a terminal. It has no window and runs until you press Ctrl+C:

```shell
xtouch-daemon virtual-device
```

Then, in another terminal, use it in place of the real X-Touch. Only one program can use it at a time, so pick one of
these two. The [self-test](first-steps.md#test-the-device) checks every control; `run` starts the daemon:

```shell
xtouch-daemon test --virtual-device         # the self-test
xtouch-daemon run --virtual-device          # the daemon, using the virtual X-Touch instead of the real one
```

`xtouch-daemon gui` can run beside them: it talks to the daemon, not to the virtual X-Touch. To always use the virtual
X-Touch, set `virtual = true` in `[device]` instead of passing `--virtual-device`.

A daemon that runs but finds no real X-Touch can switch to the virtual one without a restart. Click "Use the virtual
device" above the drawing. It sets `virtual = true` in `[device]` of your configuration file and opens the virtual
device in the window. To go back, set `virtual` to `false` and
save. The [GUI](../guides/gui.md#the-virtual-device) guide describes the bars above the drawing.
