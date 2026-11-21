# Troubleshooting

Start with the log and the state of the service:

```shell
systemctl --user status xtouch-daemon      # does the service run? (the last log lines)
journalctl --user -u xtouch-daemon -f      # the log
```

The GUI shows the same log in View → [Log](gui.md#log). It reads the log of the running daemon, so it also works for a
daemon that you started in a terminal.

A healthy start logs that the X-Touch connected (and, with a [broker](home-assistant.md), the MQTT connection). For
more detail, run the daemon in the foreground with debug messages (only one daemon can hold the X-Touch):

1. `systemctl --user stop xtouch-daemon`
2. `xtouch-daemon run -l debug` (stop it with Ctrl+C)
3. `systemctl --user start xtouch-daemon`

## Starting

**xtouch-daemon refuses to run as root.** It says `xtouch-daemon runs as your user, not as root: ...`, because the
commands of the configuration would run as root. Run it as your user, without `sudo`, e.g. as the systemd user service.
Only `schema`, `simulate`, `--help` and `--version` work as root. For several users on one machine, see
[Several users on one machine](../development/design/multiple-users.md).

**`other users can change ..., so the daemon does not use it`.** The group or others can change the configuration file
or its directory, so they could put a command into it. Remove that right, e.g. `chmod go-w
~/.config/xtouch-daemon/config.toml`. A file of another user is refused too. On a reload, the daemon logs the error and
keeps the configuration it runs.

**`other users can read ...`.** A warning: other users can read a file that holds a secret, e.g. `[mqtt] password_file`
or `[homeassistant] token_file`. The daemon still uses it. Close it with `chmod go-rw` and the path from the message.

## The X-Touch

**The LCD shows `IP: 192.168.001.100 wait...`.** The X-Touch is in a setup mode for the network and ignores USB. Switch
it to MC mode on USB in its setup menu, see [Getting started](../getting-started/first-steps.md#set-up-the-device).

**`... is it switched on, in MC mode on USB?`** The daemon (and `xtouch-daemon test`) can't find the sound card of the
X-Touch. The daemon keeps waiting and connects when the card appears. Check that the X-Touch is on and that
`/proc/asound/cards` lists it. If the card has another name, set `[device] name` to a part of that name.

**`can't open X-Touch-Ext (... Device or resource busy)`.** Another program has the X-Touch, e.g. a DAW or a MIDI tool.
Close it. While the daemon runs, `xtouch-daemon test` asks the daemon to run the test.

**`... Permission denied`.** Your user can't open the MIDI port in `/dev/snd`. Without a desktop session (SSH, headless),
add the user to the `audio` group (`sudo usermod -aG audio $USER`) and log in again. See
[Hardware](../reference/hardware.md#linux-access).

**A fader does not change the volume.** The daemon counts a move only while the X-Touch reports a touch, and the motor
pushes the fader back otherwise. `xtouch-daemon test` (or "Test the device" in the GUI) shows `touch` on the LCD while
you touch the fader; if it does not, the sensor is broken. Until you repair it,
[`touchless_faders`](../configuration/behavior.md#faders-without-a-touch-sensor) makes the fader work without it.

**A fader jumps on its first move after the daemon started.** The X-Touch can't report where its faders are, so the
daemon assumes the bottom. If you moved a fader while the daemon did not run, the first move starts from the old
position. Nothing is broken. See [Hardware](../reference/hardware.md#motor-faders).

## Audio

**The meters stay dark.** A meter moves only while something plays to the output or an application records from the
input: the meters never open a sound device themselves. Also check that `meters` of
[`[behavior]`](../configuration/behavior.md) is `true` and that the channel does not set `meter = false`.

**Streams don't follow when I select another output.** The sound server sends a stream (the audio of one application)
to the default output, and the Select button of an output strip makes that output the default. A stream that another
tool moved to a particular output (the per-stream menu of pavucontrol, `pactl move-sink-input`) stays there. Move it
back in pavucontrol, or close and reopen the audio in that application.

**A strip shows `off`.** The sound device that the strip controls is not there, e.g. Bluetooth headphones that are
switched off. The strip comes back by itself. `xtouch-daemon list-devices` shows what is there.

**An [`apps` channel](../configuration/channels/applications.md) shows `idle`.** No stream of its applications is there. `xtouch-daemon list-apps` shows the applications that play, and which channel or
[slot](../configuration/slots.md) takes each one.

**Select does not start the application of `launch`.** The log of the daemon says why. Usually the program is not in
`PATH` (`can't launch ...`), no stream of it showed up within 15 s, or the strip already counts the application as
running (on an `apps` channel, any process whose name contains a `match` entry). The output of the application is in
`journalctl --user -u 'xtouch-launch-*'`. A graphical application needs `WAYLAND_DISPLAY` or `DISPLAY` in `systemctl
--user show-environment`; most desktops import them at login.

**An application lands on the wrong strip.** `xtouch-daemon list-apps` names the channel or slot that takes it. An
`apps` channel takes every application whose name or binary contains one of its `match` entries, so a short entry can
match more than you meant. `check-config` shows what the [presets](../configuration/presets.md) stand for.

## Configuration

**A slot shows something else than I expected.** With the daemon running, `xtouch-daemon why 3` says why slot 3 shows
what it shows, and `xtouch-daemon why browser` where the channel `browser` is, see [`why`](../reference/commands.md#why).
The inspector of the slot in the GUI shows the same.

**A change does not show on the X-Touch.** If the file has errors, the daemon logs them and keeps the old configuration:
run `xtouch-daemon check-config`. A changed `[mqtt]` section needs `systemctl --user restart xtouch-daemon`. The
[GUI](gui.md#save-and-apply) tells whether the X-Touch runs the saved file.

## Home Assistant

**The entities are unavailable.** They are available only while the daemon runs and the X-Touch is connected. Check the
broker settings in `[mqtt]` and the log; the popover of the service pill in the GUI shows how the connection is doing,
and Settings, Home Assistant has "Test connection".

**The second line of a strip shows `offline`.** The strip takes its text from Home Assistant, and the daemon can't
reach it (the MQTT broker or Home Assistant). It tries again by itself. (`off` is a different state: the sound device
is missing.)

## Voice chat

**"waiting for Mumble", or nobody on the strips.** See [Mumble](mumble.md#troubleshooting) or
[TeamSpeak](teamspeak.md#troubleshooting): the plugin must be enabled in the client, and people need free slots, see
[People](../configuration/channels/people.md).

## GUI

**`xtouch-daemon gui` says how to install it.** The GUI is an extra (`xtouch-daemon[gui]`, or `xtouch-daemon-gui-bin` on
Arch), see [Install](../getting-started/install.md).

**The service pill says "unavailable".** The GUI can't ask systemd about the user service, e.g. without a systemd user
session (SSH, a container); the tooltip says why. The GUI still edits the file, and "Try without a device" needs no
daemon. (A daemon you started in a terminal shows "running elsewhere".)

**The pill says "Not on the device yet" after a save.** The daemon did not take the file; its log says why (View → Log
in the GUI, or `journalctl --user -u xtouch-daemon`).

**Next:** [Commands](../reference/commands.md), [Hardware and protocol](../reference/hardware.md).
