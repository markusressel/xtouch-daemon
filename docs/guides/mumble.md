# Mumble

With the Mumble plugin of xtouch-daemon, the [strips of people](../configuration/channels/people.md) show the people in your
Mumble channel, one per strip:

- the name on the LCD, the backlight in `talking_color` while they talk, and their voice on the meter;
- the fader sets their volume for you (0 to 200 %, `max_volume` at the top);
- Mute mutes them for you: it is Mumble's own local mute, so Mumble shows it, and a local mute you set in Mumble lights
  the button;
- people who join or leave the channel, and you moving to another channel, show at once.

It needs Mumble 1.4 or later on Linux (x86_64). People sit on the slots of `auto` (and `people`) in every configuration; the
[`[voip]`](../configuration/channels/people.md#voice-chat) section can be left out: its `provider = "bridge"` is the default.

## Setup in the GUI

The page Settings, Voice chat (the `[voip]` section) has a box "Mumble":

1. Click **Install Mumble plugin**. It copies the plugin into Mumble's plugin directory
   (`~/.local/share/Mumble/Mumble/Plugins`, or the one of the Flatpak), replacing an older one. (Without a plugin to
   install, e.g. in a checkout, the button builds it first; that needs `cmake` and a C compiler.) Mumble's own
   installer is not used: with a Mumble that runs, it starts a second instance, which crashed (Mumble 1.5.939).
2. In Mumble: **Settings**, **Plugins**, click **Reload plugins** (or restart Mumble), tick **Enable** of
   "xtouch-daemon", and **Apply**.
3. Keep `provider = "bridge"` (the default). People take free `auto` (and `people`) slots from the right; see the
   example below.
4. Join a channel. The pill of the box says **Mumble connected** and how many people are in the channel.

The pill shows what the running daemon sees: "waiting for Mumble" while the plugin is not connected (Mumble is not
running, or the plugin is not enabled), "not in use" for a daemon older than the people of `auto`.

## Setup on the command line

```shell
xtouch-daemon mumble-plugin --install
```

does what the button does (see [`mumble-plugin`](../reference/commands.md#mumble-plugin)); then step 2 above. Without
xtouch-daemon's help: in Mumble, **Settings**, **Plugins**, **Install plugin...**, and pick
`/usr/share/xtouch-daemon/xtouch-daemon.mumble_plugin` (a release) or
`integrations/mumble/build/xtouch-daemon.mumble_plugin` (a checkout, after `xtouch-daemon mumble-plugin --build`).

## Slots for Mumble

Alice always on slot 1 while she is there, the others on the `auto` slots from the right, and Mumble as one strip
with your microphone while you are in a channel:

```toml
[channel.alice]
type = "person"
person = "Alice"      # her name in Mumble

[channel.voip]
type = "apps"
match = ["mumble"]
label = "Mumble"

[channel.mic]
type = "input"

[state.call]
voice_chat = true     # in a channel of Mumble
delay_off = 5

[slots]
1 = ["alice if present", "auto"]
6 = ["voip if call", "auto"]
7 = ["mic if call", "auto"]
```

See [People and the voice chat](../configuration/channels/people.md) and [States and modes](../configuration/slots.md#states-and-modes).

To start Mumble from the device, give a slot a launch in `[controls]` with a `mumble://` URL, e.g.
`6 = { select = { launch = ["mumble", "mumble://me@voice.example.org/Gaming"] }, when = "not call" }`: Select starts
Mumble, which connects to the server and joins the channel. See
[Launching the application](../configuration/channels/applications.md#launching-the-application).

## Behavior and limits

- **Mute is Mumble's "Local Mute"** (in the menu of a user): Mute on the strip sets it, Mumble shows it in its
  window, and setting it in Mumble lights the button. Mumble tells plugins of no change of the local mute, so the
  plugin looks every half second: a mute set in Mumble reaches the button within about 0.5 s (a press of Mute on the
  strip shows at once). Should Mumble refuse a mute, the button goes back, and Mumble's log says why ("xtouch-daemon:
  can't mute ..."). A local mute set from the strip lasts while the person stays; Mumble only stores the ones set in
  its own menu (for registered users).
- **The volume is the plugin's own.** The plugin scales the voice of each person before Mumble mixes it. Mumble's own
  "Local Volume Adjustment" is separate, and the faders don't show or change it: Mumble's plugin interface has no call
  for it. The two multiply: a person at 50 % in Mumble and 50 % on the fader is at 25 %.
- **The daemon keeps them for the name.** The plugin forgets the volume of someone who leaves; the daemon remembers
  the volume and the mute the strips set for each name while it runs and sends them again when the person comes back
  (a mute changed in Mumble meanwhile replaces the one of the strip). A restart of the daemon starts everyone at
  100 %.
- **Not their own mute.** Whether other people muted or deafened themselves is not in Mumble's plugin interface: it
  tells their talking state only, and someone who muted themselves sends nothing, so they just don't talk.
- **Your channel only**, without you: nobody else's channel, no whispers to other channels.
- **The level** on the meter is the voice as it arrives, before or after the fader (`meter_point`), and before
  Mumble's own volume and positional audio. Mumble does not fetch the voice of a muted person: before the fader their
  meter lights while they talk, without a level; after it, it stays dark.

## How it works

The plugin (`integrations/mumble/plugin.c`, plugin API 1.0) connects to the socket of the daemon,
`$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`, and speaks the [bridge protocol](../reference/voice-chat-bridge.md):
the people of the channel on every change and 20 times a second while someone talks (for the levels), and the
volume and mute commands back. The plugin's socket thread never calls into Mumble; a second thread makes the calls for
the mute, which Mumble runs in its main thread (see the comment at the top of `plugin.c`). It connects again every
2 seconds while the daemon is not there, so the order in which Mumble and the daemon start does not matter. `$XTOUCH_DAEMON_VOIP_SOCKET` (in Mumble's environment) points it to
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

**Nobody on the strips:** the strips show your channel without you; join a channel with other people. People need
free `auto` slots, or `person` channels on slots (`xtouch-daemon check-config` shows which slots are `auto`).

**Two Mumble clients at once** (e.g. a second one with `mumble -m -c <other settings file>` to test with another
user): enable the plugin in one of them only. The daemon keeps the plugin that connected first and refuses the other
one; it logs "Refusing another voice chat plugin while one is connected" once.
