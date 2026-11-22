# Mumble

Mumble is a voice chat program. With the Mumble plugin of xtouch-daemon, the
[strips of people](../configuration/channels/people.md) show the people in your Mumble channel, one person per strip
(you are not one of them):

- the name on the LCD, the backlight in the color `talking_color` while they talk, and their voice on the meter;
- the fader sets their volume for you (see `max_volume` in [People](../configuration/channels/people.md#the-strips-of-people));
- Mute mutes them for you: it is Mumble's own local mute, so Mumble shows it, and a local mute you set in Mumble lights
  the button.

It needs Mumble 1.4 or later on Linux (x86_64), and xtouch-daemon installed (see [Install](../getting-started/install.md)).
The configuration needs no change: a strip without an entry in [`[slots]`](../configuration/slots.md#slots) shows the pool `auto`, and the people fill
the free strips from the right (see [Where people sit](../configuration/channels/people.md#where-people-sit)). Their
look is set in `[pool.people]`, see [People](../configuration/channels/people.md#the-strips-of-people).

The plugin talks to the daemon through [the voice chat bridge](../reference/voice-chat-bridge.md), which is on by
default (`[voip]` has `provider = "bridge"`). Set `provider = "demo"` only to try the strips without Mumble.

## Setup in the GUI

The page Settings, Voice chat (the `[voip]` section) has a box "Mumble":

1. Click **Install Mumble plugin**. (For Mumble as a Flatpak, read [Flatpak](#flatpak) as well.) It copies the plugin
   into Mumble's plugin directory (`~/.local/share/Mumble/Mumble/Plugins`, or the directory of the Flatpak),
   replacing an older one. From a git clone of the source, the button builds the plugin first: that needs `cmake` and
   a C compiler. The button does not use Mumble's own installer: while Mumble runs, that installer starts a second
   Mumble, which crashed.
2. In Mumble: **Settings**, **Plugins**, click **Reload plugins** (or restart Mumble), tick **Enable** of
   "xtouch-daemon", and **Apply**.
3. Join a channel. The status label (the "pill") in the box says **Mumble connected** and how many people are in
   the channel.

"waiting for Mumble" means that the plugin is not connected: Mumble is not running, or the plugin is not enabled.
"not in use" means that the daemon is an old version: update it.

## Setup on the command line

```shell
xtouch-daemon mumble-plugin --install
```

does what the button does (see [`mumble-plugin`](../reference/commands.md#mumble-plugin)); then do step 2 above.
Or use Mumble's own installer, only while Mumble does not run: **Settings**, **Plugins**, **Install plugin...**, and
pick `/usr/share/xtouch-daemon/xtouch-daemon.mumble_plugin`.

## Slots for Mumble

Alice gets slot 1 while she is in your channel. Mumble itself and your microphone get slots 6 and 7 while you are in
a channel (`[state.call]`). Everyone else takes the free strips from the right. (The `voip` channel can also match
with the preset `@voip`, see [Presets](../configuration/presets.md).)

```toml
[channel.alice]
type = "person"
person = "Alice"      # her name in Mumble

[channel.voip]
type = "apps"         # the sound of the Mumble program itself, as one strip
match = ["mumble"]
label = "Mumble"

[channel.mic]
type = "input"        # no `device` option: your default microphone

[state.call]
voice_chat = true
delay_off = 5         # seconds: stays on 5 s after you leave

[slots]
1 = ["alice if present", "auto"]   # Alice while she is there, else the next on auto
6 = ["voip if call", "auto"]       # Mumble while the state call is on
7 = ["mic if call", "auto"]
```

To start Mumble from the X-Touch, give a slot a `launch` in `[controls]` with a `mumble://` URL:

```toml
[controls]
6 = { select = { launch = ["mumble", "mumble://me@voice.example.org/Gaming"] }, when = "not call" }
```

Select starts Mumble only while you are in no channel. See
[Launching the application](../configuration/channels/applications.md#launching-the-application).

## Behavior and limits

- **Mute is Mumble's "Local Mute"** (in the menu of a user). Mumble does not tell plugins when it changes, so the
  plugin asks every half second: a mute set in Mumble reaches the button a moment later. If Mumble refuses a mute,
  the button goes back, and Mumble's log says why. Mumble forgets a mute set from
  the strip when the person leaves; the daemon sends it again when they come back (it remembers volume and mute by
  name while it runs, see [the bridge](../reference/voice-chat-bridge.md)). A mute you set in Mumble itself replaces
  the one of the strip.
- **The volume is the plugin's own.** Mumble's "Local Volume Adjustment" is separate, and the faders don't show or
  change it: Mumble's plugin interface has no call for it. The two multiply: 50 % in Mumble and 50 % on the fader is
  25 %. When the daemon restarts, everyone starts at 100 % again.
- **Not shown:** whether other people muted themselves (they send no voice, so the strip shows them as not talking),
  people of other channels, and whispers.
- **The meter** shows the voice as it arrives from Mumble, before Mumble's own volume and positional audio.
  `meter_point` sets whether it is measured before the fader (`"pre_fader"`) or after it (`"post_fader"`). Mumble
  does not fetch the voice of someone you muted, so there is no level: while they talk, a meter before the fader
  shows a fixed high level, and a meter after the fader stays dark.

## Flatpak

A Mumble in a Flatpak can't see the socket of the daemon (the file `xtouch-daemon-voip.sock` in your runtime
directory) by default. Allow it:

```shell
flatpak override --user --filesystem=xdg-run/xtouch-daemon-voip.sock info.mumble.Mumble
```

How the plugin works and how to build it: [Mumble plugin](../development/mumble-plugin.md).

## Troubleshooting

**"waiting for Mumble"** although Mumble runs: enable the plugin in Mumble's settings (Plugins), and check that
`xtouch-daemon mumble-plugin` (without options) prints a line "In Mumble: ..." with the path of the plugin.

**Nobody on the strips:** join a channel with other people, and keep free strips that show `auto`
(`xtouch-daemon check-config` shows which).

**Two Mumble clients at once:** enable the plugin in one of them only. The daemon keeps the plugin that connected
first and logs "Refusing another voice chat plugin of mumble while one is connected".

Next: [Applications](../configuration/channels/applications.md#launching-the-application) (start Mumble with Select), [People](../configuration/channels/people.md) (where people sit).
