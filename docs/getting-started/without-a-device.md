# Without a device

A virtual X-Touch Extender stands in for the device, e.g. to follow the [Setup tour](tour.md) before the device
arrives, to try a configuration, or while the device is away. It speaks the bytes of the real one, so the daemon does
the same with it, down to faders that wait for a touch; [Hardware](../reference/hardware.md#the-virtual-device) lists
what it does like the device and what is assumed.

## In the GUI

```shell
xtouch-daemon gui
```

"Try without a device" above the drawing starts a daemon with the virtual device inside the window: the drawing is the
device, and the mouse on it is a hand on it (**Play**: press a fader to touch it, drag to move it, click a button; see
[GUI](../guides/gui.md#select-and-play)). The daemon ends with the window. Nothing else to set up.

## In terminals

```shell
xtouch-daemon virtual-device                # the device, headless, until Ctrl+C
xtouch-daemon test --virtual-device         # the self-test of the device, see First steps
xtouch-daemon run --virtual-device          # or [device] virtual = true: the daemon drives it
xtouch-daemon gui                           # shows what the daemon shows
```

The pill on the bar of the window Device in the GUI says "virtual device not running · Open it" while the daemon
waits for the device: a click opens it in the window, and the mouse on the drawing is a hand on the device (see
[GUI](../guides/gui.md#the-virtual-device)). One daemon at a time can use the virtual device.

A daemon that runs but finds no device switches to the virtual one without a restart: "Use the virtual device" above
the drawing sets `[device] virtual = true`, saves and opens it, and Play on a daemon that waits for the virtual device
opens it too. Setting `virtual` back to `false` and saving switches to the real device again.
