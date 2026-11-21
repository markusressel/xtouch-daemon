# TeamSpeak plugin

How the TeamSpeak 3 plugin of xtouch-daemon works and how to build it. For using it, see the
[TeamSpeak guide](../guides/teamspeak.md).

## How it works

The plugin (`integrations/teamspeak/plugin.c`, plugin API 26, the one of TeamSpeak 3.6) connects to the socket of
the daemon, `$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`, and speaks the
[bridge protocol](../reference/voice-chat-bridge.md) with `"client": "teamspeak"`. It sends the people of the
channel on every change, and 20 times a second while someone talks (for the levels). It takes the volume and mute
commands back. It connects again every 2 seconds while the daemon is not there, so the order in which TeamSpeak and
the daemon start does not matter. `$XTOUCH_DAEMON_VOIP_SOCKET` (in TeamSpeak's environment) points it to another
socket. It works like the [Mumble plugin](mumble-plugin.md); the differences:

| | TeamSpeak plugin |
|---|---|
| Server | The shown server tab (`getCurrentServerConnectionHandlerID`) if it is connected, else the first connected one (`getServerConnectionHandlerList`). `currentServerConnectionChanged` and `onConnectStatusChangeEvent` pick again. |
| People | `getChannelClientList` of the channel of `getClientID`, without the user and without ServerQuery clients (`CLIENT_TYPE`). The id is TeamSpeak's client id, the name `CLIENT_NICKNAME`. |
| Talking | `onTalkStatusChangeEvent`: `STATUS_TALKING`, whispers included. |
| Volume | TeamSpeak's volume modifier (`setClientVolumeModifier`, `CLIENT_VOLUME_MODIFICATOR`), in dB: `20 * log10(percent / 100)`, so 50 % is −6.02 dB and 200 % is +6.02 dB. 0 % is −60 dB, and the plugin sets the samples to 0 itself. This is the gain the Mumble plugin applies, as decibels. TeamSpeak tells the modifier as a whole number, so a modifier read within 1 dB of the one set counts as unchanged; one further away came from TeamSpeak's window and moves the fader. |
| Mute | `requestMuteClients` and `requestUnmuteClients`, read back with `CLIENT_IS_MUTED`. For 1.5 s after a request, the plugin trusts it over what it reads: the server may take a moment. |
| Levels | `onEditPlaybackVoiceDataEvent`: 16-bit samples of each person, every 10 ms while they talk. Its peak is `pre_fader_level`, and `level` is that peak times `percent / 100`. |

TeamSpeak sends no event when a mute or a volume changes in its window. So, while the daemon is connected, the plugin
reads both every 500 ms.

**Where the volume applies.** TeamSpeak's documentation says that `onEditPlaybackVoiceDataEvent` comes "before it
is 3D positioned and mixed with other sounds", and says nothing of the volume modifier. A plugin developer on
TeamSpeak's forum calls this stream the "pre-processing" one, and the volume modifiers part of the post-processing.
The plugin relies on that. If the modifier applied before the callback, `pre_fader_level` would be after the fader
too, and `level` would count the volume twice.

### Threads

TeamSpeak calls the callbacks in its own threads, the voice ones in its audio thread. They take the plugin's lock
for a moment and make no calls into TeamSpeak. A callback that changes the channel or its people only marks the
channel as stale. The plugin has two threads:

- `work()` does the socket and never calls TeamSpeak. It queues the commands of the daemon.
- `follow_teamspeak()` makes every call into TeamSpeak. It reads the channel again when it is stale, sets the
  queued volumes and mutes, and reads the mutes and volumes every 500 ms.

No thread holds the lock during a call into TeamSpeak, so a callback never waits for one. `ts3plugin_shutdown` waits
for both threads: `work()` ends within 50 ms, and `follow_teamspeak()` after the call it is making, if any.

A client that leaves the channel is forgotten in the callback. TeamSpeak may still list it for a moment, so the next
reads leave it out until TeamSpeak no longer lists it, or until it moves back into the channel.

## Building it

```shell
cmake -S integrations/teamspeak -B integrations/teamspeak/build
cmake --build integrations/teamspeak/build
```

This makes `xtouch-daemon_linux_amd64.so`, the same as `xtouch-daemon teamspeak-plugin --build`. Releases have it in
`/usr/share/xtouch-daemon/`, and CI builds it on every push.

**The SDK.** The plugin needs the headers of TeamSpeak's plugin SDK
([ts3client-pluginsdk](https://github.com/TeamSpeak-Systems/ts3client-pluginsdk), plugin API 26). They are not in
this repository: the SDK has no license, and its README says "Copyright © TeamSpeak Systems GmbH. All rights
reserved." The first configure downloads it from GitHub, at a pinned commit, and checks it against a SHA-256 hash
(both in `CMakeLists.txt`). It goes into `integrations/teamspeak/sdk/`, which git ignores, so later builds work
offline. `-DTS3_SDK_DIR=<directory>` uses another copy of the SDK (the directory with `include/ts3_functions.h`).

## Testing it

`tests/voip/test_teamspeak_plugin.py` builds the plugin with `-DXTD_TESTS=ON`, which also builds
`integrations/teamspeak/test/fake_teamspeak.c`. The fake loads the plugin like TeamSpeak does, gives it a table of
functions of made-up servers, and calls its callbacks as a script on stdin says. The plugin runs against a real
`BridgeProvider`. The fake aborts on a call into TeamSpeak from a callback, or after `ts3plugin_shutdown`. Functions
the fake does not have are NULL. The tests are skipped without `cmake` and a C compiler, or when the SDK can't be
downloaded. They never use a real TeamSpeak.
