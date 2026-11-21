# TeamSpeak

With the TeamSpeak plugin of xtouch-daemon, the [strips of people](../configuration/channels/people.md) show the
people in your TeamSpeak channel, one per strip:

- the name on the LCD, the backlight in `talking_color` while they talk, and their voice on the meter;
- the fader sets their volume (0 to 200 %, `max_volume` at the top): it is TeamSpeak's own "Change Volume", so
  TeamSpeak keeps it, and a volume you change in TeamSpeak moves the fader;
- Mute is TeamSpeak's "Mute Client": TeamSpeak shows it, and a mute you set in TeamSpeak lights the button;
- people who join or leave the channel, and you moving to another channel, show at once.

It needs the TeamSpeak 3 client 3.6 or later on Linux (x86_64), e.g. the Arch package `teamspeak3`. The plugin does
not work with TeamSpeak 5 or 6. People sit on the slots of `auto` (and `people`) in every configuration; the
[`[voip]`](../configuration/channels/people.md#voice-chat) section can be left out: its `provider = "bridge"` is the
default.

## Setup in the GUI

The page Settings, Voice chat (the `[voip]` section) has a box "TeamSpeak":

1. Click **Install TeamSpeak plugin**. It copies `xtouch-daemon_linux_amd64.so` into `~/.ts3client/plugins`,
   replacing an older one. Without a plugin to install, e.g. in a checkout, it builds one first. That needs `cmake`,
   a C compiler and, the first time, the internet: the build downloads the headers of TeamSpeak's plugin SDK.
2. In TeamSpeak: **Tools**, **Options**, **Addons**. Click **Reload All** (or restart TeamSpeak), find
   "xtouch-daemon" under the plugins, and enable it.
3. Keep `provider = "bridge"` (the default). People take free `auto` (and `people`) [slots](../configuration/slots.md) from the right; see the
   [example for Mumble](mumble.md#slots-for-mumble), which works the same with `match = ["teamspeak", "ts3client"]`
   for the strip of the application.
4. Connect to a server and join a channel. The pill of the box says **TeamSpeak connected** and how many people are
   in the channel.

The pill shows what the running daemon sees: "waiting for TeamSpeak" while no plugin is connected, "not connected"
while the plugin of another client is. Without TeamSpeak on the machine the box has one line: "not installed".

## Setup on the command line

```shell
xtouch-daemon teamspeak-plugin --install
```

does what the button does (see [`teamspeak-plugin`](../reference/commands.md#teamspeak-plugin)); then step 2 above.

The daemon logs "Voice chat plugin connected (teamspeak)" when the plugin connects.

## Behavior and limits

- **One server.** With several server tabs, the strips show the tab you look at, if it is connected; else the first
  connected tab. Switching tabs switches the people.
- **The volume is TeamSpeak's.** The fader sets the volume TeamSpeak shows under "Change Volume" in the menu of a
  person. The plugin turns the percent into decibels: 100 % is 0 dB, 50 % is −6 dB, 200 % is +6 dB. At 0 % the
  plugin silences the person itself (TeamSpeak's volume then is −60 dB). A volume set in TeamSpeak reaches the fader
  within about 0.5 s. TeamSpeak tells it in whole decibels, so the fader can be off by up to 6 %.
- **Mute is TeamSpeak's "Mute Client".** Mute on the strip sets it, and TeamSpeak shows it. TeamSpeak tells plugins
  of no change of it, so the plugin looks every half second: a mute set in TeamSpeak reaches the button within about
  0.5 s. Should TeamSpeak refuse a mute or a volume, the button or fader goes back, and TeamSpeak's log (**Tools**,
  **Client Log**) says why ("xtouch-daemon: can't mute ...").
- **The level** on the meter is the voice as it arrives (before the fader, `meter_point = "pre"`), or that voice
  times the volume of the fader (after it). It leaves out TeamSpeak's own playback volume and 3D sound. TeamSpeak's
  server sends no voice of a muted person, so their meter stays dark.
- **Not their own mute.** Whether other people muted their microphone or speakers is not shown: they just don't
  talk.
- **Your channel only**, without you and without ServerQuery clients: no whispers from other channels.
- **Mumble and TeamSpeak together.** Both plugins can be connected at once: the strips show the people of both
  channels. See [the voice chat bridge](../reference/voice-chat-bridge.md). The daemon takes one plugin per client:
  with the plugin enabled in two TeamSpeak clients, it keeps the one that connected first.

How the plugin works and how to build it: [TeamSpeak plugin](../development/teamspeak-plugin.md).

## Troubleshooting

**No people on the strips** although TeamSpeak runs: check that the plugin is enabled in TeamSpeak (**Tools**,
**Options**, **Addons**), and that `xtouch-daemon teamspeak-plugin` says "In TeamSpeak: ..." with a path. TeamSpeak
loads only plugins of its plugin API (26 for TeamSpeak 3.6); an older TeamSpeak says the plugin failed to load. The
strips show your channel without you: join a channel with other people. People need free `auto` slots, or `person`
[channels](../configuration/channels/index.md) on slots (`xtouch-daemon check-config` shows which slots are `auto`).

**The build fails with "Can't download TeamSpeak's plugin SDK":** connect to the internet for the first build, or
give a copy of the SDK with `cmake -DTS3_SDK_DIR=<directory>` (see [TeamSpeak plugin](../development/teamspeak-plugin.md#building-it)).

Next: [People](../configuration/channels/people.md) (where people sit), [Applications](../configuration/channels/applications.md#launching-the-application) (start TeamSpeak with Select).
