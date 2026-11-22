# First steps

Set up the X-Touch Extender, test it, write a configuration and run the daemon as a service. No X-Touch Extender at hand? See
[Without a physical control surface](without-a-device.md).

## Set up the control surface { #set-up-the-device }

The X-Touch Extender has to be in **MC** (Mackie Control) mode on **USB**. Out of the box it may be set to the network
interface: then it shows `IP: 192.168.001.100 wait...` and ignores USB.

1. Switch it off.
2. Hold the **Select** button of strip 1 and switch it on: the setup menu opens.
3. Set **Mode** to `MC` and **Interface** to `USB` with the encoders.
4. Leave the menu (Select of strip 1 again, or switch it off and on).

Connect it over USB. It needs no driver. Your user needs access to it: a desktop session grants that to the logged-in
user. See [Hardware](../reference/hardware.md#linux-access) for other cases.

## Test the control surface { #test-the-device }

```shell
xtouch-daemon test
```

Every strip lights its LCD, LEDs, ring and meter, and moves its fader. Afterwards every strip answers its own
controls ([`test`](../reference/commands.md#test) has the details). Ctrl+C stops it.

A running service does not need to stop: `xtouch-daemon test` asks the daemon to run the test. Close DAWs that use
the control surface.

## Write a configuration

A configuration defines **channels** (what a strip can control), **states** (in a call, gaming) and, for each of the 8
slots, what its strip shows when. [Concepts](../concepts.md) explains these words. Without a file the daemon uses the
[example configuration](../configuration/index.md).

The easiest way to make it yours is the [GUI](../guides/gui.md): it shows the control surface live and every option with its
help, and "Save and apply" writes the file and loads it into the running daemon. [How to start it](install.md#the-gui).
The [Setup tour](tour.md) builds a whole configuration that way, step by step.

To work by hand, let `init-config` write the example file, then edit it:

```shell
xtouch-daemon init-config                 # writes ~/.config/xtouch-daemon/config.toml
xtouch-daemon list-devices [--snippet]    # the names of outputs and inputs (--snippet: channels to paste)
xtouch-daemon list-apps                   # the applications that play now, and which channel or slot takes them
xtouch-daemon check-config                # validates the file (with the line of each error) and shows what each slot shows when
```

For editor completion, see [Editors and AI assistants](../configuration/index.md#editors-and-ai-assistants).

For example, Bluetooth headphones on slot 1 while they are connected, and VoIP on slot 2 during a call:

```toml
[channel.buds]
type = "output"
device = "bluez_output.*"   # your Bluetooth headphones (the name holds an address; list-devices shows it)
label = "Buds"
color = "green"

[channel.voip]
type = "apps"
match = ["@voip"]   # Discord, Mumble, TeamSpeak and more, see Presets
label = "VoIP"

[state.call]
voice_chat = true   # on while you are in a voice chat channel (Mumble or TeamSpeak, with its plugin: see [Mumble](../guides/mumble.md) and [TeamSpeak](../guides/teamspeak.md))

[slots]
1 = ["buds if present", "auto"]
2 = ["voip if call", "auto"]
# slots 3 to 8 have no entry: "auto", the next application that plays or a person of the voice chat
```

`check-config` shows what this file does, as a table:

```
when               1     2     3-8
default            buds  auto  auto
call               buds  voip  auto
buds absent        auto  auto  auto
call, buds absent  auto  voip  auto
```

Each row is a situation. In `default`, `call` is off and `buds` is there; the other rows change one of the two.
[Channels, states and slots](../configuration/slots.md) explains the format.

## Run it as a service

```shell
xtouch-daemon install-service --now
```

This writes the systemd user unit and starts it with your session. The Arch Linux package has its own unit; enable
that one instead:

```shell
systemctl --user enable --now xtouch-daemon
```

The daemon runs as your user: don't start it with `sudo`. See
[`install-service`](../reference/commands.md#install-service). If it refuses to start, see
[Troubleshooting](../guides/troubleshooting.md#starting).

| Task | Command |
|---|---|
| Apply a changed configuration | Nothing: the daemon takes the saved file. By hand: `systemctl --user reload xtouch-daemon` |
| Restart (after changing `[mqtt]`, the settings of your MQTT broker, which only Home Assistant needs) | `systemctl --user restart xtouch-daemon` |
| Stop (the control surface then goes dark, and another program can use it) | `systemctl --user stop xtouch-daemon` |
| See whether the control surface, the sound server and, with Home Assistant, the MQTT broker are connected | `systemctl --user status xtouch-daemon` |
| Follow the log | `journalctl --user -u xtouch-daemon -f`, or View → Log in the GUI |

To run it in the foreground, e.g. to watch the log:

```shell
xtouch-daemon run -l debug
```

Next: the [Setup tour](tour.md), then [Concepts](../concepts.md).
