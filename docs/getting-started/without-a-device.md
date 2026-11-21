# Without a device

A virtual X-Touch Extender stands in for the real one. You can use it to follow the [Setup tour](tour.md) before your
X-Touch arrives, to try a configuration, or while the X-Touch is away. It sends and understands the same bytes as the
real X-Touch, so the daemon treats it like the real one. [Hardware](../reference/hardware.md#the-virtual-device) lists
what it does like the X-Touch and what is assumed.

There are two ways to use it: in the GUI, which is the easy one, or in terminals.

## In the GUI

```shell
xtouch-daemon gui
```

The GUI shows a drawing of the X-Touch. While no daemon runs, click the button "Try without a device" above the
drawing. The GUI then starts a daemon that uses a virtual X-Touch, which the GUI calls the **virtual device** and
shows in the drawing. Nothing else needs setting up. This daemon belongs to the window and ends when you close
the window.

The mouse works on the drawing like a hand on the X-Touch. This mode is called **Play**: press a fader to touch it,
drag to move it, click a button. [GUI](../guides/gui.md#select-and-play) has the details.

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

While the daemon runs, `xtouch-daemon gui` shows what the daemon shows. It does not count as a second program: it talks to the daemon, not to the virtual X-Touch. To make the daemon use the virtual X-Touch
every time, set `virtual = true` in the `[device]` section of the configuration instead of passing
`--virtual-device`.

A daemon that runs but finds no real X-Touch can switch to the virtual one without a restart. Click "Use the virtual
device" above the drawing. It sets `virtual = true` in `[device]` of your configuration file and opens the virtual
device in the window. To go back, set `virtual` to `false` and
save. The [GUI](../guides/gui.md#the-virtual-device) guide describes the bars above the drawing.
