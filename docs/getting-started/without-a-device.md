# Without a device

A virtual X-Touch Extender stands in for the device, e.g. to try a configuration or while the device is away:

```shell
xtouch-daemon run --virtual-device   # or [device] virtual = true
xtouch-daemon gui
```

While the daemon waits for it, the pill on the bar of the window Device in the GUI says "virtual device not running ·
Open it": a click opens it, and the mouse on the drawing is a hand on the device (see
[GUI](../guides/gui.md#the-virtual-device)). Without a daemon running, "Try without a device" above the drawing does both at
once (see [GUI](../guides/gui.md#select-and-play)). `xtouch-daemon virtual-device` runs one without the GUI. The virtual device
speaks the bytes of the real one, so the daemon does the same with it, down to faders that wait for a touch;
[Hardware](../reference/hardware.md#the-virtual-device) lists what it does like the device and what is assumed.

A daemon that runs but finds no device switches to the virtual one without a restart: "Use the virtual device" above
the drawing sets `[device] virtual = true`, saves and opens it, and Play on a daemon that waits for the virtual device
opens it too. Setting `virtual` back to `false` and saving switches to the real device again.
