# Without a device

A virtual X-Touch Extender stands in for the real one. You can use it to follow the [Setup tour](tour.md) before the
device arrives, to try a configuration, or while the device is away. It sends and understands the same bytes as the
real device, so the daemon treats it like the real one. For example, its motor never moves a fader while a finger touches it.
[Hardware](../reference/hardware.md#the-virtual-device) lists what it does like the device and what is assumed.

There are two ways to use it: in the GUI, which is the easy one, or in terminals.

## In the GUI

```shell
xtouch-daemon gui
```

The GUI shows a drawing of the device. While no daemon runs, click the button "Try without a device" above the
drawing. The GUI then starts a daemon with a virtual device and shows that device in the drawing. Nothing else needs
setting up. This daemon belongs to the window and ends when you close the window.

The mouse works on the drawing like a hand on the device. This mode is called **Play**: press a fader to touch it,
drag to move it, click a button. [GUI](../guides/gui.md#select-and-play) has the details.

## In terminals

First start the virtual device in a terminal. It has no window and runs until you press Ctrl+C:

```shell
xtouch-daemon virtual-device
```

Then, in another terminal, use it in place of the real device. Only one program can use the virtual device at a time,
so pick one of these two. The [self-test](first-steps.md#test-the-device) checks every control of the device; `run`
starts the daemon:

```shell
xtouch-daemon test --virtual-device         # the self-test of the device
xtouch-daemon run --virtual-device          # the daemon, using the virtual device instead of the real one
```

While the daemon runs, `xtouch-daemon gui` shows what the daemon shows. The GUI talks to the daemon, not to the virtual
device, so it does not count as a second user of it. To make the daemon use the
virtual device every time, set `virtual = true` in the `[device]` section of the configuration instead of passing
`--virtual-device`.

Suppose you start `run --virtual-device` (or set `virtual = true`) but forget `virtual-device`. The GUI can host the
virtual device instead. The status pill on the right of the Device bar, at the top of the drawing, says "virtual device not running · Open it". Click it, and the GUI opens a virtual device in its
window. It is the same kind of device as the one `virtual-device` starts, but it lives in the window, not in a terminal. The daemon connects to it, and Play
works on it (see [GUI](../guides/gui.md#the-virtual-device)).

## When the daemon finds no device

A daemon that runs but finds no real device can use the virtual one without a restart. In the GUI, click "Use the
virtual device" above the drawing. It sets `virtual = true` in `[device]` of your configuration file, saves the file and opens the virtual device
in the window. The daemon takes it at once.

To go back, set `virtual` to `false` and save. Later, whenever the real device is plugged in while the daemon uses the
virtual one, a bar above the drawing says so.
Click "Switch to it" in that bar, and the daemon uses the real device again.
