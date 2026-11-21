# Mumble

Mumble is a voice chat program. With the Mumble plugin of xtouch-daemon, the
[strips of people](../configuration/channels/people.md) show the people in your Mumble channel, one person per strip
(you are not one of them):

- the name on the LCD, the backlight in the color `talking_color` while they talk, and their voice on the meter;
- the fader sets their volume for you (0 to `max_volume` percent, at most 200 %; `max_volume` is the volume with the fader at the top);
- Mute mutes them for you: it is Mumble's own local mute, so Mumble shows it, and a local mute you set in Mumble lights
  the button;
- people who join or leave the channel, and you moving to another channel, show at once.

It needs Mumble 1.4 or later on Linux (x86_64), and xtouch-daemon installed (see [Install](../getting-started/install.md)).

You need no changes to the configuration file for this. A strip that has no entry in `[slots]` shows `auto`, and
`auto` is a pool: a supplier that hands out strips to what it holds, the people of the voice chat and the applications
that play. The people fill the free strips from the right (8, 7, 6 and so on), the applications from the left
(1, 2, 3 and so on); a strip goes to one or the other, never both.

The plugin talks to the daemon through the bridge: a socket that the daemon opens for plugins of voice chat programs
(see [the voice chat bridge](../reference/voice-chat-bridge.md)). The bridge is on by default (`[voip]` has
`provider = "bridge"`). You change it only to try the strips without Mumble (`provider = "demo"`).

The look of the people has these options. The lines below show the defaults. The default of `max_volume` is the
option `max_volume` in the section [`[behavior]`](../configuration/behavior.md) of the configuration, which is 130:
with it the fader goes from 0 to 130 %, and you set 200 to reach 200 %. Change the options in `[pool.people]` for
all people, or in a `person` channel for one person (see [People](../configuration/channels/people.md)):

```toml
[pool.people]
talking_color = "green"   # the backlight while they talk
max_volume = 130          # percent, 200 at most: the volume with the fader at the top
meter_point = "pre_fader" # the meter shows the voice before the fader ("post_fader": after it)
```

## Setup in the GUI

The page Settings, Voice chat (the `[voip]` section) has a box "Mumble":

1. Click **Install Mumble plugin**. (For Mumble as a Flatpak, read [Flatpak](#flatpak) below as well.) It copies the plugin into Mumble's plugin directory
   (`~/.local/share/Mumble/Mumble/Plugins`, or the directory of the Flatpak), replacing an older one. If you run
   xtouch-daemon from a git clone of the source, there is no built plugin to copy, and the button builds it first:
   that needs `cmake` and a C compiler. The button does not use Mumble's own installer: when Mumble runs, that
   installer starts a second Mumble, which crashed (in version 1.5.939). Other versions may work, but the button does
   not take the risk.
2. In Mumble: **Settings**, **Plugins**, click **Reload plugins** (or restart Mumble), tick **Enable** of
   "xtouch-daemon", and **Apply**.
3. Nothing to do in the configuration: the people take the free strips from the right. The example below pins
   some of them to a strip.
4. Join a channel. The status label (the "pill") in the box says **Mumble connected** and how many people are in
   the channel.

The pill shows what the running daemon sees. "waiting for Mumble" means that the plugin is not connected: Mumble is
not running, or the plugin is not enabled. "not in use" means that the daemon is an old version that does not show
people yet; update it. A fresh install of a current version never shows it.

## Setup on the command line

```shell
xtouch-daemon mumble-plugin --install
```

does what the button does (see [`mumble-plugin`](../reference/commands.md#mumble-plugin)); then do step 2 above.
Without xtouch-daemon's help, you can use Mumble's own installer instead (only while Mumble does not run, because of
the crash above): in Mumble, **Settings**, **Plugins**, **Install plugin...**, and pick
`/usr/share/xtouch-daemon/xtouch-daemon.mumble_plugin` (a release) or
`integrations/mumble/build/xtouch-daemon.mumble_plugin` (a checkout, after `xtouch-daemon mumble-plugin --build`).

## Slots for Mumble

This example pins three things. A person called Alice gets slot 1 while she is in your channel. Mumble itself and
your microphone get slots 6 and 7 while you are in a channel. All other people sit on the free strips from the
right (the slots that show `auto`: here 2 to 5 and 8, which have no entry, and also 1, 6 and 7 whenever their first
candidate does not apply):

```toml
[channel.alice]
type = "person"
person = "Alice"      # her name in Mumble

[channel.voip]
type = "apps"         # the sound of the Mumble program itself, as one strip
match = ["mumble"]
label = "Mumble"

[channel.mic]
type = "input"        # no device: your default microphone

[state.call]
voice_chat = true     # on while you are in a channel of Mumble
delay_off = 5         # seconds: stays on 5 s after you leave

[slots]
1 = ["alice if present", "auto"]   # Alice while she is there, else the next on auto
6 = ["voip if call", "auto"]       # Mumble while the state call is on
7 = ["mic if call", "auto"]
```

`alice`, `voip` and `mic` are channels, `call` is a state, `auto` is the pool. The strips 1, 6 and 7 show other people
while their first candidate does not apply (Alice is not there, `call` is off). While it applies, the other people
skip those strips and take 8, 5, 4 and so on.

See [People and the voice chat](../configuration/channels/people.md) and [States and modes](../configuration/slots.md#states-and-modes).

To start Mumble from the device, give a slot a `launch` (the command that its Select button runs) in `[controls]`
with a `mumble://` URL (the `[controls]` section sets what the buttons of a slot do, whatever the slot shows):

```toml
[controls]
6 = { select = { launch = ["mumble", "mumble://me@voice.example.org/Gaming"] }, when = "not call" }
```

`when = "not call"` means that the entry acts only while you are in no voice chat channel. Select then starts Mumble,
which connects to the server and joins the channel. See
[Launching the application](../configuration/channels/applications.md#launching-the-application).

## Behavior and limits

- **Mute is Mumble's "Local Mute"** (in the menu of a user): Mute on the strip sets it, Mumble shows it in its
  window, and setting it in Mumble lights the button. Mumble does not tell plugins when the local mute changes, so
  the plugin asks every half second: a mute set in Mumble reaches the button within about 0.5 s (a press of Mute on
  the strip shows at once). If Mumble refuses a mute, the button goes back, and Mumble's log says why
  ("xtouch-daemon: can't mute ..."). A mute set from the strip works while the person is in the channel. Mumble forgets it when the
  person leaves (Mumble keeps a local mute only if you set it in its own menu, and only for a user who is registered
  on the server). The next item says what the daemon does about it.
- **The volume is the plugin's own.** The plugin scales the voice of each person before Mumble mixes it. Mumble's own
  "Local Volume Adjustment" is separate, and the faders don't show or change it: Mumble's plugin interface has no call
  for it. The two multiply: a person at 50 % in Mumble and 50 % on the fader is at 25 %.
- **The daemon remembers volume and mute by name.** This makes the volume and the mute of the strips last longer than
  Mumble keeps them. The plugin forgets the volume of someone who leaves. The daemon
  remembers the volume and the mute that the strips set for each name, as long as it runs, and sends them again when
  the person comes back; Mumble forgets, the daemon does not. (If you change the mute in Mumble yourself, that mute replaces the one of the strip.) When the daemon
  restarts, everyone starts at 100 % again.
- **No display of their own mute.** The strips do not show whether other people muted or deafened themselves.
  Mumble's plugin interface does not report it. Someone who muted themselves sends no voice, so the strip shows them
  as not talking.
- **Your channel only.** The strips show the people of your channel, without you. They show nobody from other
  channels, and no whispers to other channels.
- **The level** on the meter is the voice as it arrives from Mumble, before Mumble's own volume and positional audio (3D sound).
  `meter_point` (see the options above) sets whether it is measured before the fader (`"pre_fader"`) or after it (`"post_fader"`,
  the voice times the volume of the fader). Mumble does not fetch the voice of someone you muted. A meter before the fader
  still lights while that person talks, because Mumble reports the talking, but it shows no level. A meter after the
  fader stays dark, because the voice times the volume is silent.

## Flatpak

A Mumble in a Flatpak can't see the socket of the daemon (the file `xtouch-daemon-voip.sock` in your runtime
directory) by default. Allow it:

```shell
flatpak override --user --filesystem=xdg-run/xtouch-daemon-voip.sock info.mumble.Mumble
```

How the plugin works and how to build it: [Mumble plugin](../development/mumble-plugin.md).

## Troubleshooting

**"waiting for Mumble"** although Mumble runs: check that the plugin is enabled in Mumble's settings (Plugins), and
that `xtouch-daemon mumble-plugin` (without options) prints a line "In Mumble: ..." with the path of the plugin. The daemon logs "Voice chat plugin connected
(mumble)" when it connects.

**Nobody on the strips:** the strips show your channel without you; join a channel with other people. People need
free strips that show `auto`, or `person` channels on slots (`xtouch-daemon check-config` shows which slots are `auto`).

**Two Mumble clients at once** (a second Mumble program, e.g. one with `mumble -m -c <other settings file>` to test with another
user): enable the plugin in one of them only. The daemon keeps the plugin that connected first and refuses the other
one; it logs "Refusing another voice chat plugin of mumble while one is connected" once. A plugin of another client,
e.g. TeamSpeak, can be connected besides it.

Next: [Applications](../configuration/channels/applications.md#launching-the-application) (start Mumble with Select), [People](../configuration/channels/people.md) (where people sit).
