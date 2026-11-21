# TeamSpeak

TeamSpeak is a voice chat program. With the TeamSpeak plugin of xtouch-daemon, the
[strips of people](../configuration/channels/people.md) show the people in your TeamSpeak channel, one person per
strip (you are not one of them):

- the name on the LCD, the backlight in the color `talking_color` while they talk, and their voice on the meter;
- the fader sets their volume (see `max_volume` in [People](../configuration/channels/people.md#the-strips-of-people)):
  it is TeamSpeak's own "Change Volume", so TeamSpeak keeps it, and a volume you change in TeamSpeak moves the fader;
- Mute is TeamSpeak's "Mute Client": TeamSpeak shows it, and a mute you set in TeamSpeak lights the button.

It needs the TeamSpeak 3 client 3.6 or later on Linux (x86_64), e.g. the Arch package `teamspeak3`, and
xtouch-daemon installed (see [Install](../getting-started/install.md)). The plugin does not work with TeamSpeak 5 or 6.

The configuration needs no change: a strip without an entry in `[slots]` shows the pool `auto`, and the people fill
the free strips from the right (see [Slots](../configuration/slots.md#pools-of-applications-and-of-people)). Their
look is set in `[pool.people]`, see [People](../configuration/channels/people.md#the-strips-of-people).

The plugin talks to the daemon through [the voice chat bridge](../reference/voice-chat-bridge.md), which is on by
default (`[voip]` has `provider = "bridge"`). Set `provider = "demo"` only to try the strips without TeamSpeak.

## Setup in the GUI

The page Settings, Voice chat (the `[voip]` section) has a box "TeamSpeak":

1. Click **Install TeamSpeak plugin**. It copies `xtouch-daemon_linux_amd64.so` into `~/.ts3client/plugins`,
   replacing an older one. From a git clone of the source, the button builds the plugin first. That needs `cmake`, a
   C compiler and, the first time, the internet: the build downloads the headers of TeamSpeak's plugin SDK.
2. In TeamSpeak: **Tools**, **Options**, **Addons**. Click **Reload All** (or restart TeamSpeak), find
   "xtouch-daemon" under the plugins, and enable it.
3. Connect to a server and join a channel. The status label (the "pill") in the box says **TeamSpeak connected** and
   how many people are in the channel.

To pin a person or the program itself to a strip, use the [example for Mumble](mumble.md#slots-for-mumble). In its
`[channel.voip]`, write `match = ["teamspeak", "ts3client"]`.

The pill says "waiting for TeamSpeak" while no plugin is connected, and "not connected" while only the plugin of
another voice chat program is. Neither is an error. Without TeamSpeak on the machine, the box says "not installed".

## Setup on the command line

```shell
xtouch-daemon teamspeak-plugin --install
```

does what the button does (see [`teamspeak-plugin`](../reference/commands.md#teamspeak-plugin)); then do step 2
above. You do not restart the daemon.

## Behavior and limits

- **One server.** With several server tabs, the strips show the tab you look at, if it is connected; else the first
  connected tab. Switching tabs switches the people.
- **The volume is TeamSpeak's.** The fader sets the "Change Volume" of the person: 100 % is 0 dB, 50 % is −6 dB,
  200 % is +6 dB, and at 0 % the person is silent. TeamSpeak reports whole decibels only, so the fader can be off by
  up to about 6 % from the true value. A volume set in TeamSpeak reaches the fader within about 0.5 s.
- **Mute** works the same way: TeamSpeak does not tell plugins when it changes, so a mute set in TeamSpeak reaches
  the button within about 0.5 s. If TeamSpeak refuses a mute or a volume, the button or fader goes back, and
  TeamSpeak's log (**Tools**, **Client Log**) says why.
- **The meter** shows the voice as it arrives, before the fader (`meter_point = "pre_fader"`) or after it
  (`"post_fader"`), without TeamSpeak's own playback volume and 3D sound. TeamSpeak sends no voice of a person you
  muted, so their meter stays dark.
- **Not shown:** whether other people muted themselves (they just do not talk), people of other channels, whispers,
  and ServerQuery clients (the invisible connections of server tools, such as bots).
- **Mumble and TeamSpeak together.** Both plugins can be connected at once: the strips show the people of both
  channels. The daemon accepts one plugin for each voice chat program: with two TeamSpeak clients, it keeps the
  plugin that connected first and refuses the other.

How the plugin works and how to build it: [TeamSpeak plugin](../development/teamspeak-plugin.md).

## Troubleshooting

**No people on the strips** although TeamSpeak runs: enable the plugin in TeamSpeak (**Tools**, **Options**,
**Addons**), and check that `xtouch-daemon teamspeak-plugin` (without options) prints a line "In TeamSpeak: ..." with
the path of the plugin. TeamSpeak loads only plugins of its plugin API (26 for TeamSpeak 3.6): an older TeamSpeak
says the plugin failed to load. Join a channel with other people, and keep free slots that show `auto`
(`xtouch-daemon check-config` shows which). The daemon logs "Voice chat plugin connected (teamspeak)" when it
connects.

**The build fails with "Can't download TeamSpeak's plugin SDK":** connect to the internet for the first build, or
give a copy of the SDK with `cmake -DTS3_SDK_DIR=<directory>` (see [TeamSpeak plugin](../development/teamspeak-plugin.md#building-it)).

Next: [People](../configuration/channels/people.md) (where people sit), [Applications](../configuration/channels/applications.md#launching-the-application) (start TeamSpeak with Select).
