# TeamSpeak

TeamSpeak is a voice chat program. With the TeamSpeak plugin of xtouch-daemon, the
[strips of people](../configuration/channels/people.md) show the people in your TeamSpeak channel, one person per
strip (you are not one of them):

- the name on the LCD, the backlight in the color `talking_color` while they talk, and their voice on the meter;
- the fader sets their volume (0 to `max_volume` percent, at most 200 %; `max_volume` is the volume with the fader at the top): it is TeamSpeak's own "Change Volume", so
  TeamSpeak keeps it, and a volume you change in TeamSpeak moves the fader;
- Mute is TeamSpeak's "Mute Client": TeamSpeak shows it, and a mute you set in TeamSpeak lights the button;
- people who join or leave the channel, and you moving to another channel, show at once.

It needs the TeamSpeak 3 client 3.6 or later on Linux (x86_64), e.g. the Arch package `teamspeak3`, and
xtouch-daemon installed (see [Install](../getting-started/install.md)). The plugin does not work with TeamSpeak 5 or 6.

You need no changes to the configuration file for this. A strip that has no entry in `[slots]` shows `auto`, and
`auto` is a pool: a supplier that hands out strips to what it holds: the people of the voice chat and the applications that play. The people fill the free strips from the right (8, 7, 6 and so on), the applications from the left
(1, 2, 3 and so on); a strip goes to one or the other, never both.

The plugin talks to the daemon through the bridge: a socket that the daemon opens for plugins of voice chat programs
(see [the voice chat bridge](../reference/voice-chat-bridge.md)). The bridge is on by default (`[voip]` has
`provider = "bridge"`). You change it only to try the strips without TeamSpeak (`provider = "demo"`).

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

The page Settings, Voice chat (the `[voip]` section) has a box "TeamSpeak":

1. Click **Install TeamSpeak plugin**. It copies `xtouch-daemon_linux_amd64.so` into `~/.ts3client/plugins`,
   replacing an older one. If you run xtouch-daemon from a git clone of the source, there is no built plugin to
   copy, and the button builds it first. That needs `cmake`, a C compiler and, the first time, the internet: the
   build downloads the headers of TeamSpeak's plugin SDK.
2. In TeamSpeak: **Tools**, **Options**, **Addons**. Click **Reload All** (or restart TeamSpeak), find
   "xtouch-daemon" under the plugins, and enable it.
3. Nothing to do in the configuration: the people take the free [slots](../configuration/slots.md) that show `auto`,
   from the right. To pin a person to a strip, see the [example for Mumble](mumble.md#slots-for-mumble); it works
   the same for TeamSpeak. That example also has an optional strip for the program itself (`[channel.voip]`): for
   TeamSpeak, write `match = ["teamspeak", "ts3client"]` in it (the names of the TeamSpeak program).
4. Connect to a server and join a channel. The status label (the "pill") in the box says **TeamSpeak connected** and
   how many people are in the channel.

The pill shows what the running daemon sees: "waiting for TeamSpeak" while no plugin is connected, and "not
connected" while only the plugin of another voice chat program (e.g. Mumble) is. Neither is an error; join a channel
in TeamSpeak with the plugin enabled. Without TeamSpeak on the machine, the box has
one line: "not installed".

## Setup on the command line

```shell
xtouch-daemon teamspeak-plugin --install
```

does what the button does (see [`teamspeak-plugin`](../reference/commands.md#teamspeak-plugin)); then do step 2
above. You do not restart the daemon. When the plugin connects, the daemon logs "Voice chat plugin connected
(teamspeak)" (see [Troubleshooting](troubleshooting.md) for how to read the log).

## Behavior and limits

- **One server.** With several server tabs, the strips show the tab you look at, if it is connected; else the first
  connected tab. Switching tabs switches the people.
- **The volume is TeamSpeak's.** The fader sets the volume TeamSpeak shows under "Change Volume" in the menu of a
  person. The plugin turns the percent into decibels: 100 % is 0 dB, 50 % is −6 dB, 200 % is +6 dB. At 0 % the
  plugin silences the person itself (TeamSpeak's volume then shows −60 dB). You do not need to do anything about that. A volume set in TeamSpeak reaches the fader
  within about 0.5 s. TeamSpeak reports the volume in whole decibels only. One decibel is a change of about 12 % of the volume,
  so rounding to a whole decibel can put the fader off by up to about 6 % from the true value.
- **Mute is TeamSpeak's "Mute Client".** Mute on the strip sets it, and TeamSpeak shows it. TeamSpeak does not tell
  plugins when a mute changes, so the plugin asks every half second: a mute set in TeamSpeak reaches the button within about
  0.5 s. Should TeamSpeak refuse a mute or a volume, the button or fader goes back, and TeamSpeak's log (**Tools**,
  **Client Log**) says why ("xtouch-daemon: can't mute ...").
- **The level** on the meter is the voice as it arrives (before the fader: `meter_point = "pre_fader"`), or that
  voice times the volume of the fader (after the fader: `"post_fader"`). The option `meter_point` is in
  `[pool.people]` or a `person` channel. The level leaves out TeamSpeak's own playback volume and 3D sound. TeamSpeak's
  server sends no voice of a person that you muted, so their meter stays dark.
- **No display of their own mute.** The strips do not show whether other people muted their microphone or speakers:
  they just do not talk.
- **Your channel only.** The strips show the people of your channel, without you and without ServerQuery clients
  (the invisible helper connections of server tools, such as bots). They show nobody from other channels, and no
  whispers.
- **Mumble and TeamSpeak together.** Both plugins can be connected at once: the strips show the people of both
  channels. See [the voice chat bridge](../reference/voice-chat-bridge.md). The daemon accepts one plugin for each
  voice chat program (one Mumble, one TeamSpeak): if you run two TeamSpeak clients with the plugin enabled, it keeps
  the plugin that connected first and refuses the other.

How the plugin works and how to build it: [TeamSpeak plugin](../development/teamspeak-plugin.md).

## Troubleshooting

**No people on the strips** although TeamSpeak runs: check that the plugin is enabled in TeamSpeak (**Tools**,
**Options**, **Addons**), and that `xtouch-daemon teamspeak-plugin` (without options) prints a line "In TeamSpeak: ..." with the path of the
plugin. TeamSpeak
loads only plugins of its plugin API (26 for TeamSpeak 3.6); an older TeamSpeak says the plugin failed to load. The
strips show your channel without you: join a channel with other people. People need free slots that show `auto`, or `person`
[channels](../configuration/channels/people.md#strips-for-one-person) on slots (`xtouch-daemon check-config` shows
which slots show `auto`). If all 8 slots show something else, no person has a strip.

**The build fails with "Can't download TeamSpeak's plugin SDK":** connect to the internet for the first build, or
give a copy of the SDK with `cmake -DTS3_SDK_DIR=<directory>` (see [TeamSpeak plugin](../development/teamspeak-plugin.md#building-it)).

Next: [People](../configuration/channels/people.md) (where people sit), [Applications](../configuration/channels/applications.md#launching-the-application) (start TeamSpeak with Select).
