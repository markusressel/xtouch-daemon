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

Every strip lights its LCD in a color, its LEDs, ring and meter, and moves its fader. Afterwards the command shows what
you do on the device: faders, buttons and encoders. Ctrl+C stops it.

Only one program can use the device. Stop the daemon before the test (`systemctl --user stop xtouch-daemon`), and close
DAWs that use it.

## Write a configuration

Without a configuration file the daemon uses the example configuration: six `auto` slots, the default input and the
default output. To change it, write the example to `~/.config/xtouch-daemon/config.toml` and edit it:

```shell
xtouch-daemon init-config     # writes ~/.config/xtouch-daemon/config.toml
xtouch-daemon list-devices    # the names to use for device channels, and the profiles of the sound cards
xtouch-daemon list-apps       # the applications that play now, and which channel or slot takes them
xtouch-daemon check-config    # validates the file and shows what each slot shows when
```

A channel is something a strip can control, a slot is a strip of the device, and states (in a call, gaming) decide
what each slot shows. For example:

```toml
[channel.buds]
type = "output"
device = "bluez_output.4C_D7_3A_EA_02_76.1"
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

[Channels, states and slots](../configuration/slots.md) explains the format, [Configuration](../configuration/index.md)
every option. The GUI (`xtouch-daemon gui`) edits it in a window; see [GUI](../guides/gui.md).

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

A unit in `~/.config/systemd/user` (e.g. from an installation from the source) overrides the one of the package.
`xtouch-daemon install-service --remove-override` removes it, so does "Use the packaged unit" in the [GUI](../guides/gui.md#the-service).

| Task | Command |
|---|---|
| Apply a changed configuration | `xtouch-daemon check-config && systemctl --user reload xtouch-daemon` |
| Restart (after changing `[device] name` or `[mqtt]`) | `systemctl --user restart xtouch-daemon` |
| Stop (e.g. for `xtouch-daemon test`) | `systemctl --user stop xtouch-daemon` |
| See whether the device, sound server and broker are connected | `systemctl --user status xtouch-daemon` |
| Follow the log | `journalctl --user -u xtouch-daemon -f` |

To run it in the foreground instead, e.g. to watch the log while you try something:

```shell
xtouch-daemon run -l debug
```
