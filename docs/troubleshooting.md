# Troubleshooting

Start with the log and the state of the service:

```shell
systemctl --user status xtouch-daemon      # is the device, the sound server, the broker connected?
journalctl --user -u xtouch-daemon -f      # the log
```

For more detail, stop the service and run the daemon in the foreground with `xtouch-daemon run -l debug`.

## The device

**The device shows `IP: 192.168.001.100 wait...`.** It is set to its network interface and ignores USB. Switch it to
MC mode on USB in its setup menu, see [Getting started](getting-started.md#set-up-the-device).

**`... is it switched on, in MC mode on USB?`** `xtouch-daemon test` can't find the sound card of the extender. The
daemon waits for it and connects when it appears. Check that it is connected and on, and that `/proc/asound/cards` lists it. If the name differs, set
`[device] name` to a part of it.

**`can't open X-Touch-Ext (... Device or resource busy)`.** Only one program can use the device. Stop the daemon
before `xtouch-daemon test` (`systemctl --user stop xtouch-daemon`), and close DAWs or other MIDI tools that opened it.

**`... Permission denied`.** Your user can't open the MIDI device in `/dev/snd`. Desktop sessions give access to the
logged-in user; without a session, add the user to the `audio` group. See [Hardware](hardware.md#linux-access).

**A fader does not change the volume.** Only a touched fader changes a value. A fader whose touch sensor failed goes
back to its value after a move. `xtouch-daemon test` shows whether the device reports `fader touched`. Until the
sensor is repaired, [`touchless_faders`](configuration/behavior.md#faders-without-a-touch-sensor) makes the fader work
without it.

**A fader jumps on its first move after the daemon started.** The device can't tell where its faders are, so after a
connect the daemon assumes them at the bottom. A fader moved while the daemon did not run jumps from where it really
is. See [Hardware](hardware.md#motor-faders).

## Audio

**The meters stay dark.** A meter shows a level only while something plays to the output or records from the input.
That is on purpose: the meters never open a device themselves. A microphone meter moves only while an application
records from it. Check also `behavior.meters` and the strip's `meter`.

**Streams don't follow when I select another output.** Select makes the device the default, and streams without a
fixed target follow the default. A stream that another tool moved to a particular device (pavucontrol's per-stream
output menu, `pactl move-sink-input`) stays there. Move it back in pavucontrol, or restart the application's stream.

**A strip shows `off`.** The device it controls is not there, e.g. Bluetooth headphones that are switched off. It
comes back by itself. `xtouch-daemon list-devices` shows the devices that are there.

**An `apps` strip shows `idle`.** No stream of its applications is there. `xtouch-daemon list-apps` shows the names
and binaries of the applications that play, and which strip takes each one.

**An application lands on the wrong strip.** `xtouch-daemon list-apps` names the strip that takes it. An `apps` strip
takes every application whose name or binary contains one of its `match` entries, so a short entry can match more than
intended.

## Configuration

**A change does not show on the device.** Reload the daemon after saving: `systemctl --user reload xtouch-daemon`. A
file with errors is logged and the old configuration stays: run `xtouch-daemon check-config`. A changed `[device] name` or
`[mqtt]` section needs a restart. The [GUI](gui.md) tells whether the device runs the saved file.

## Home Assistant

**The entities are unavailable.** They are available only while the daemon runs and the device is connected. Check
the broker settings in `[mqtt]` and the log. The GUI tells how the connection is doing next to the preview and on the
page "Home Assistant", where "Test connection" tries the settings.

**A strip shows `offline`.** The broker can't be reached. The daemon connects again by itself.
