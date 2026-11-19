# First steps

Set up the device, test it, write a configuration and run the daemon as a service. No device at hand? See
[Without a device](without-a-device.md).

## Set up the device

The extender has to be in **MC** (Mackie Control) mode on **USB**. Out of the box it may be set to the network
interface: then it shows `IP: 192.168.001.100 wait...` and ignores USB.

1. Switch it off.
2. Hold the **Select** button of strip 1 and switch it on: the setup menu opens.
3. Set **Mode** to `MC` and **Interface** to `USB` with the encoders.
4. Leave the menu (Select of strip 1 again, or switch it off and on).

Connect it over USB. It needs no driver. Your user needs access to its MIDI device in `/dev/snd`: desktop sessions
grant it to the logged-in user. Without a session, add the user to the `audio` group. See
[Hardware](../reference/hardware.md#linux-access) for details.

## Test the device

```shell
xtouch-daemon test
```

Every strip lights its LCD in a color, its LEDs, ring and meter, and moves its fader. Afterwards every strip answers
its own controls: the meter follows the fader, a button steps its LED, the encoder changes the ring, the LCD color and
the motor fader ([`test`](../reference/commands.md#test) has the details). Ctrl+C stops it.

If the daemon already runs as a service, it runs the test (the slots show again after it). Close DAWs that use the
device. Without a device, start the virtual one in another terminal (`xtouch-daemon virtual-device`) and run
`xtouch-daemon test --virtual-device`; see [Without a device](without-a-device.md).

## Write a configuration

A configuration names **channels** (what a strip can control), **states** (in a call, gaming) and, for each of the 8
slots, what its strip shows when. [Concepts](../concepts.md) explains these words. Without a file the daemon uses the
[example configuration](../configuration/index.md): the default input on slot 7, the default output on slot 8, and
`auto` (the next application that plays) on the others. To make it yours, the easiest way is the [GUI](../guides/gui.md) (`xtouch-daemon-gui` or `xtouch-daemon gui`): it shows the device live, every option with its help, and what a change does (**Simulate**); its
"Save and apply" writes the file and loads it into the running daemon.

[Setup tour](tour.md) builds a whole configuration that way, step by step, with the file it writes.

By hand, write the example to `~/.config/xtouch-daemon/config.toml` and edit it:

```shell
xtouch-daemon init-config                 # writes ~/.config/xtouch-daemon/config.toml
xtouch-daemon list-devices [--snippet]    # the names to use for device channels (--snippet: channels to paste)
xtouch-daemon list-apps                   # the applications that play now, and which channel or slot takes them
xtouch-daemon check-config                # validates the file (with the line of each error) and shows what each slot shows when
```

An editor with a TOML language server completes the options of the file and shows their help: see
[Editors and AI assistants](../configuration/index.md#editors-and-ai-assistants).

For example, Bluetooth headphones on slot 1 while they are connected, and VoIP on slot 2 during a call:

```toml
[channel.buds]
type = "output"
device = "bluez_output.*"   # any Bluetooth headphones (their name holds an address; list-devices shows it)
label = "Buds"
color = "green"

[channel.voip]
type = "apps"
match = ["@voip"]   # Discord, Mumble, TeamSpeak and more, see Presets
label = "VoIP"

[state.call]
voice_chat = true   # in a channel of Mumble (with the plugin)

[slots]
1 = ["buds if present", "auto"]
2 = ["voip if call", "auto"]
# slots 3 to 8 have no entry: "auto", the next application that plays
```

`check-config` shows what this file does, as a table:

```
when               1     2     3-8
default            buds  auto  auto
call               buds  voip  auto
buds absent        auto  auto  auto
call, buds absent  auto  voip  auto
```

A row for each situation the slots ask about (`call`, whether `buds` is there) that changes something.

[Channels, states and slots](../configuration/slots.md) explains the format, [Configuration](../configuration/index.md)
every option.

## Run it as a service

```shell
xtouch-daemon install-service --now
```

This writes the systemd user unit `~/.config/systemd/user/xtouch-daemon.service`, enables it and starts it. From now on
it starts with your session. Without `--now` it only writes the unit.

The Arch Linux package has its own unit, so with it the command writes nothing: it enables and starts the unit of the
package. The same without the command:

```shell
systemctl --user enable --now xtouch-daemon
```

A unit in `~/.config/systemd/user` overrides the one of the package; see
[`install-service`](../reference/commands.md#install-service).

| Task | Command |
|---|---|
| Apply a changed configuration | Nothing: the daemon takes the saved file. By hand: `systemctl --user reload xtouch-daemon` |
| Restart (after changing `[mqtt]`) | `systemctl --user restart xtouch-daemon` |
| Stop (e.g. for `xtouch-daemon test`) | `systemctl --user stop xtouch-daemon` |
| See whether the device, sound server and broker are connected | `systemctl --user status xtouch-daemon` |
| Follow the log | `journalctl --user -u xtouch-daemon -f`, or View → Log in the GUI |

To run it in the foreground instead, e.g. to watch the log while you try something:

```shell
xtouch-daemon run -l debug
```

Next: the [Setup tour](tour.md), then [Concepts](../concepts.md).
