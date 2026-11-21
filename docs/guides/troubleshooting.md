# Troubleshooting

Start with the log and the state of the service:

```shell
systemctl --user status xtouch-daemon      # does the service run? (the last log lines)
journalctl --user -u xtouch-daemon -f      # the log
```

The GUI shows the same log in View → [Log](gui.md#log). It reads the log of the running daemon, so it also works for a
daemon that you started in a terminal.

A healthy start logs that the X-Touch connected (and, with a [broker](home-assistant.md), the MQTT connection). For
more detail, run the daemon in the foreground with debug messages. Only one daemon can hold the X-Touch, so stop the
service first:

1. `systemctl --user stop xtouch-daemon`
2. `xtouch-daemon run -l debug` (stop it with Ctrl+C)
3. `systemctl --user start xtouch-daemon`

## Starting

**xtouch-daemon refuses to run as root.** It says `xtouch-daemon runs as your user, not as root: ...`. The commands
of the configuration would run as root. Run it as your user, without `sudo`, e.g. as the systemd user service. Only
`schema`, `simulate`, `--help` and `--version` work as root. Every other command refuses to run. If several users share the machine, see [Several users on one machine](../development/design/multiple-users.md).

**`other users can change ..., so the daemon does not use it`.** The group or others can change the configuration
file or its directory. Someone else could put a command into it, and the daemon would run it as you. Remove
that right with `chmod`, e.g. `chmod go-w ~/.config/xtouch-daemon/config.toml`. A file that belongs to another
user is refused too (`... belongs to ..., not to you`). When the daemon reloads the configuration, it logs the error
and keeps the configuration it runs.

**`other users can read ...`.** This is a warning. Other users can read a file that holds a secret, e.g. the file of `[mqtt] password_file` or
`[homeassistant] token_file`. The daemon still uses it. Close it to others with `chmod go-rw` and the path from the
message.

## The X-Touch

**The LCD of the X-Touch shows `IP: 192.168.001.100 wait...`.** The X-Touch is in a setup mode that talks over the network (Ethernet) and ignores
USB. This is a setting of the X-Touch, not of your computer. Switch it to
MC mode on USB in its setup menu, as described in [Getting started](../getting-started/first-steps.md#set-up-the-device).

**`... is it switched on, in MC mode on USB?`** The daemon (and `xtouch-daemon test`) can't find the sound card of the
X-Touch. This is not fatal: the daemon keeps waiting and connects when the card appears. Check that the X-Touch is connected and on, and
that `/proc/asound/cards` lists it. If the card has another name than the default, set `[device] name` to a part of
the name in that list.

**`can't open X-Touch-Ext (... Device or resource busy)`.** Only one program can use the X-Touch at a time, and another program has it. Close DAWs or other
MIDI tools that opened it. The command `xtouch-daemon test` is not one of them while the daemon runs: it then asks
the daemon, which has the X-Touch, to run the test.

**`... Permission denied`.** Your user can't open the MIDI port of the X-Touch in `/dev/snd`. Desktop sessions give access to the
logged-in user; without a session (e.g. over SSH, or a headless machine), add the user to the `audio` group with
`sudo usermod -aG audio $USER`, then log in again. See [Hardware](../reference/hardware.md#linux-access).

**A fader does not change the volume.** The daemon counts a fader move only while the X-Touch reports a finger on the
fader (the touch sensor). If the sensor of one fader is broken, the daemon ignores your move and the motor pushes the
fader back to its old value shortly after. `xtouch-daemon test` (or "Test the device" in the GUI) shows `touch` on the
LCD while the X-Touch reports a touch: touch the fader and look. If `touch` does not show, the sensor of that fader is
broken. Until you can repair the X-Touch, [`touchless_faders`](../configuration/behavior.md#faders-without-a-touch-sensor) makes the fader work
without it.

**A fader jumps on its first move after the daemon started.** The X-Touch can't tell the computer where its faders
are, so after a connect the daemon assumes that they are all at the bottom. If you moved a fader while the daemon did
not run, the fader is somewhere else, and the first move starts from there: the volume jumps to that position.
Nothing is broken: after that first move, the fader and the volume agree. See [Hardware](../reference/hardware.md#motor-faders).

## Audio

**The meters stay dark.** A meter shows a level only while something plays to the output or records from the input.
That is on purpose: the meters never open a sound device themselves. A microphone meter moves only while an application
records from it. Also check that the option `meters` of [`[behavior]`](../configuration/behavior.md) is `true` and
that the channel does not set `meter = false`.

**Streams don't follow when I select another output.** A stream is the audio that one application plays. The sound
server (PipeWire or PulseAudio) sends a stream to the default output, unless something fixed another output for it
(a stream that a tool moved to your speakers, say). A stream that is not fixed
follows the default. The Select button of an output strip makes that output the default (the `select` option of the
channel can change what the button does), so the streams move with it. A stream that another tool moved to a
particular output (the per-stream output menu of pavucontrol, `pactl move-sink-input`) stays there. Move it back in
pavucontrol, or close and reopen the audio in that application.

**A strip shows `off`.** The sound device that the strip controls is not there, e.g. Bluetooth headphones that are
switched off. The strip comes back by itself when it does. `xtouch-daemon list-devices` shows the outputs and inputs that are there.

**An [`apps` channel](../configuration/channels/applications.md) shows `idle`.** No stream of its applications is there. `xtouch-daemon list-apps` shows the names
and binaries of the applications that play, and which channel or [slot](../configuration/slots.md) takes each one.

**Select does not start the application of `launch`.** `launch` is an option of a channel: the command that its
Select button runs. The log of the daemon says why nothing started:

- The program is not in `PATH` (`can't launch ...`).
- The program started, but no stream of it showed up within 15 s.
- The strip already counts the application as running, so Select does nothing. On an `apps` channel, any running
  process whose name contains one of the `match` entries counts (`ps -eo comm` lists the names).

The output of the application is in `journalctl --user -u 'xtouch-launch-*'`. The daemon starts the application under the systemd user manager, not in your desktop session. A graphical
application can only open a window if the manager knows the variables of your desktop: `systemctl --user show-environment` should list `WAYLAND_DISPLAY` or `DISPLAY`. Most desktops import them at
login.

**An application lands on the wrong strip.** `xtouch-daemon list-apps` names the channel or slot that takes it. An
`apps` channel takes every application whose name or binary contains one of its `match` entries, so a short entry can
match more than you meant. `check-config` shows what the [presets](../configuration/presets.md) in `match` stand for.

## Configuration

**A slot shows something else than I expected.** These two commands ask the running daemon, so start it first:

- `xtouch-daemon why 3` says why slot 3 shows what it shows, and why it does not show each candidate above it.
- `xtouch-daemon why browser` says where the channel with the id `browser` (the name in `[channel.browser]`) is now, and why it is not on other slots.

The GUI shows the same in the inspector of the slot. `xtouch-daemon check-config` shows what the slots show in each
situation.

**A change does not show on the X-Touch.** The daemon takes a saved file a moment later. If the file has errors, the
daemon logs them and keeps the old configuration: run `xtouch-daemon check-config` to see them. A changed `[mqtt]`
section needs a restart of the service (`systemctl --user restart xtouch-daemon`). The [GUI](gui.md) tells whether the X-Touch runs the saved file.

## Home Assistant

**The entities are unavailable.** They are available only while the daemon runs and the X-Touch is connected. Check
the broker settings in `[mqtt]` and the log. The GUI shows how the connection is doing in the
popover of the service pill (the status label in the header of the window that shows whether the daemon runs), and on the page Settings, Home Assistant, where "Test connection" tries the settings.

**The second line of a strip shows `offline`.** The strip takes its text from Home Assistant, and the daemon can't
reach it (the MQTT broker or Home Assistant). It tries again by itself. (`off` is a different state: the sound device
is missing.)

## Voice chat

**"waiting for Mumble", or nobody on the strips.** See [Mumble](mumble.md#troubleshooting) or
[TeamSpeak](teamspeak.md#troubleshooting): the plugin must be enabled in the client, and people need free slots that show
`auto` (a slot without an entry does) or `person` channels on slots.

## GUI

**`xtouch-daemon gui` says how to install it.** The GUI is an extra (`xtouch-daemon[gui]`, or `xtouch-daemon-gui-bin` on
Arch), see [Install](../getting-started/install.md).

**The service pill says "unavailable".** The GUI can't ask systemd about the user service, e.g. because there is no
systemd user session (over SSH, in a container). The tooltip of the pill says why. (A daemon that you started in a
terminal shows "running elsewhere" instead; the GUI reloads it when you save.) The GUI edits the configuration file
without the service, and "Try without a device" needs no daemon.

**The pill says "Not on the device yet" after a save.** (The GUI calls the X-Touch "the device".) The daemon did not take the file; its log says why
(View → Log in the GUI, or `journalctl --user -u xtouch-daemon`).

**Next:** [Commands](../reference/commands.md), [Hardware and protocol](../reference/hardware.md).
