# Troubleshooting

Start with the log and the state of the service:

```shell
systemctl --user status xtouch-daemon      # is the device, the sound server, the broker connected?
journalctl --user -u xtouch-daemon -f      # the log
```

For more detail, stop the service and run the daemon in the foreground with `xtouch-daemon run -l debug`.

## The device

**The device shows `IP: 192.168.001.100 wait...`.** It is set to its network interface and ignores USB. Switch it to
MC mode on USB in its setup menu, see [Getting started](../getting-started/first-steps.md#set-up-the-device).

**`... is it switched on, in MC mode on USB?`** `xtouch-daemon test` can't find the sound card of the extender. The
daemon waits for it and connects when it appears. Check that it is connected and on, and that `/proc/asound/cards` lists it. If the name differs, set
`[device] name` to a part of it.

**`can't open X-Touch-Ext (... Device or resource busy)`.** Only one program can use the device. Close DAWs or other
MIDI tools that opened it. (`xtouch-daemon test` asks a running daemon to run the test.)

**`... Permission denied`.** Your user can't open the MIDI device in `/dev/snd`. Desktop sessions give access to the
logged-in user; without a session, add the user to the `audio` group. See [Hardware](../reference/hardware.md#linux-access).

**A fader does not change the volume.** Only a touched fader changes a value. A fader whose touch sensor failed goes
back to its value after a move. `xtouch-daemon test` (or "Test the device" in the GUI) shows `touch` on the LCD
when the device reports the touch. Until the
sensor is repaired, [`touchless_faders`](../configuration/behavior.md#faders-without-a-touch-sensor) makes the fader work
without it.

**A fader jumps on its first move after the daemon started.** The device can't tell where its faders are, so after a
connect the daemon assumes them at the bottom. A fader moved while the daemon did not run jumps from where it really
is. See [Hardware](../reference/hardware.md#motor-faders).

## Audio

**The meters stay dark.** A meter shows a level only while something plays to the output or records from the input.
That is on purpose: the meters never open a device themselves. A microphone meter moves only while an application
records from it. Check also `behavior.meters` and the strip's `meter`.

**Streams don't follow when I select another output.** Select makes the device the default, and streams without a
fixed target follow the default. A stream that another tool moved to a particular device (pavucontrol's per-stream
output menu, `pactl move-sink-input`) stays there. Move it back in pavucontrol, or restart the application's stream.

**A strip shows `off`.** The device it controls is not there, e.g. Bluetooth headphones that are switched off. It
comes back by itself. `xtouch-daemon list-devices` shows the devices that are there.

**An [`apps` channel](../configuration/channels/applications.md) shows `idle`.** No stream of its applications is there. `xtouch-daemon list-apps` shows the names
and binaries of the applications that play, and which channel or [slot](../configuration/slots.md) takes each one.

**Select does not start the application of `launch`.** The daemon's log says why: a program that is not in `PATH`
(`can't launch ...`), or one that did not show up in 15 s. Nothing happens either while the strip counts it as
running: on `apps` channels also a process whose name contains a `match` entry (`ps -eo comm` shows them). The
application's own output is in `journalctl --user -u 'xtouch-launch-*'`. A graphical application that finds no
display there needs the desktop's variables in the systemd user manager (`systemctl --user show-environment`
should list `WAYLAND_DISPLAY` or `DISPLAY`); most desktops import them at login.

**An application lands on the wrong strip.** `xtouch-daemon list-apps` names the channel or slot that takes it. An
`apps` channel takes every application whose name or binary contains one of its `match` entries, so a short entry can match more than
intended. `check-config` shows what the [presets](../configuration/presets.md) in `match` stand for.

## Configuration

**A slot shows something else than I expected.** `xtouch-daemon why 3` says why slot 3 shows what it shows, and why
not each candidate above it; `xtouch-daemon why browser` where the channel is and why not elsewhere. The GUI shows
the same in the inspector of the slot. `xtouch-daemon check-config` shows what the slots show in each situation.

**A change does not show on the device.** The daemon takes a saved file a moment later. A file with errors is
logged and the old configuration stays: run `xtouch-daemon check-config`. A changed `[mqtt]` section
needs a restart. The [GUI](gui.md) tells whether the device runs the saved file.

## Home Assistant

**The entities are unavailable.** They are available only while the daemon runs and the device is connected. Check
the broker settings in `[mqtt]` and the log. The GUI tells how the connection is doing in the
popover of the service pill, and on the page Settings, Home Assistant, where "Test connection" tries the settings.

**A strip shows `offline`.** The broker can't be reached. The daemon connects again by itself.

## Voice chat

**"waiting for Mumble", or nobody on the strips.** See [Mumble](mumble.md#troubleshooting): the plugin must be enabled in
Mumble, and people need free `auto` slots or `person` channels on slots.

## GUI

**`xtouch-daemon gui` says how to install it.** The GUI is an extra (`xtouch-daemon[gui]`, or `xtouch-daemon-gui-bin` on
Arch), see [Install](../getting-started/install.md).

**The service pill says "unavailable".** The daemon is not running as a systemd user service. Start it with
`systemctl --user start xtouch-daemon`, or run it in the foreground. The GUI edits the file without it, and "Try without a
device" needs none.

**"The device does not run the saved file yet" stays.** The daemon did not take the file; its log says why
(`journalctl --user -u xtouch-daemon`).

**Next:** [Commands](../reference/commands.md), [Hardware and protocol](../reference/hardware.md).
