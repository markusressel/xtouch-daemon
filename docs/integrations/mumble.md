# Mumble

With the Mumble plugin of xtouch-daemon, [`voip` strips](../configuration/layouts.md#voip-strips) show the people in
your Mumble channel, one per strip:

- the name on the LCD, the backlight in `talking_color` while they talk, and their voice on the meter;
- the fader sets their volume for you (0 to 200 %, `max_volume` of the strip at the top);
- Mute mutes them for you;
- people who join or leave the channel, and you moving to another channel, show at once.

It needs Mumble 1.4 or later on Linux (x86_64), and a configuration with `voip` strips. Their
[`[voip]`](../configuration/layouts.md#voice-chat) section can be left out: its `provider = "bridge"` is the default.

## Setup in the GUI

The page "Voice chat" of the global settings (the `[voip]` section) has a box "Mumble":

1. Click **Install Mumble plugin**. Mumble opens a dialog that asks whether to install the plugin: confirm. (Without a
   plugin to install, e.g. in a checkout, the button builds it first; that needs `cmake` and a C compiler.)
2. In Mumble: **Settings**, **Plugins**, click **Reload plugins** (or restart Mumble), tick **Enable** of
   "xtouch-daemon", and **Apply**.
3. In the GUI: keep `provider = "bridge"`, and give a layout `voip` strips (see the example below). Save.
4. Join a channel. The pill of the box says **Mumble connected** and how many people are in the channel.

The pill shows what the running daemon sees: "waiting for Mumble" while the plugin is not connected (Mumble is not
running, or the plugin is not enabled), "not in use" for a daemon without `voip` strips or a `[voip]` section.

## Setup on the command line

```shell
xtouch-daemon mumble-plugin --install
```

does what the button does (see [`mumble-plugin`](../commands.md#mumble-plugin)); then step 2 above. Without
xtouch-daemon's help: in Mumble, **Settings**, **Plugins**, **Install plugin...**, and pick
`/usr/share/xtouch-daemon/xtouch-daemon.mumble_plugin` (a release) or
`integrations/mumble/build/xtouch-daemon.mumble_plugin` (a checkout, after `xtouch-daemon mumble-plugin --build`).

## A layout for Mumble

A layout that comes while Mumble runs, with five people on strips 1 to 5 and the rest of the default layout:

```toml
[voip]
provider = "bridge"

[[layout]]
name = "mumble"
label = "Mumble"
processes = ["mumble"]

[[layout.strip]]
type = "voip"
count = 5

[[layout.strip]]
type = "inherit"
```

More than five people: Select pages through them. See [Layouts](../configuration/layouts.md) for the rules and the
other ways to switch.

## What it does, and what not

- **Volume and mute are the plugin's own.** The plugin scales the voice of each person before Mumble mixes it, and
  silences a muted one. Mumble's own "Local Volume Adjustment" and "Local Mute" (in the menu of a user) are separate,
  and the faders don't show or change them: Mumble's plugin interface has no call for the volume, and the plugin
  makes no calls that could wait for Mumble. The two multiply: a person at 50 % in Mumble and 50 % on the fader is
  at 25 %.
- **They last while the person is in the channel.** Someone who leaves and comes back starts at 100 %, not muted.
- **Your channel only**, without you: nobody else's channel, no whispers to other channels.
- **The level** on the meter is the voice as it arrives (after the fader), before Mumble's own volume and positional
  audio.

## How it works

The plugin (`integrations/mumble/plugin.c`, plugin API 1.0) connects to the socket of the daemon,
`$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`, and speaks the [bridge protocol](../configuration/layouts.md#the-bridge-protocol):
the people of the channel on every change and 20 times a second while someone talks (for the levels), and the
volume and mute commands back. It connects again every 2 seconds while the daemon is not there, so the order in which
Mumble and the daemon start does not matter. `$XTOUCH_DAEMON_VOIP_SOCKET` (in Mumble's environment) points it to
another socket.

**Flatpak:** a Mumble in a Flatpak can't see the socket by default. Let it:

```shell
flatpak override --user --filesystem=xdg-run/xtouch-daemon-voip.sock info.mumble.Mumble
```

## Building it

```shell
cmake -S integrations/mumble -B integrations/mumble/build
cmake --build integrations/mumble/build
```

makes `libxtouch-daemon.so` and the bundle `xtouch-daemon.mumble_plugin` (the library and a `manifest.xml`, as Mumble
installs plugins), the same as `xtouch-daemon mumble-plugin --build`. The releases have it built in
`/usr/share/xtouch-daemon/`, CI builds it on every push. The plugin header `integrations/mumble/include/MumblePlugin.h`
is Mumble's (from Mumble 1.5.939, BSD-3-Clause, see `include/LICENSE.mumble`).

## Troubleshooting

**"waiting for Mumble"** although Mumble runs: check that the plugin is enabled in Mumble's settings (Plugins), and
that `xtouch-daemon mumble-plugin` says "In Mumble: ..." with a path. The daemon logs "Voice chat plugin connected
(mumble)" when it connects.

**Nobody on the strips:** the strips show your channel without you; join a channel with other people. The layout with
the `voip` strips has to be the one shown (`xtouch-daemon layout`).

