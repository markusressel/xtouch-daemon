# Mumble plugin

How the Mumble plugin of xtouch-daemon works and how to build it. For using it, see the [Mumble guide](../guides/mumble.md).

## How it works

The plugin (`integrations/mumble/plugin.c`, plugin API 1.0) connects to the socket of the daemon,
`$XDG_RUNTIME_DIR/xtouch-daemon-voip.sock`, and speaks the [bridge protocol](../reference/voice-chat-bridge.md):
the people of the channel on every change and 20 times a second while someone talks (for the levels), and the
volume and mute commands back. The plugin's socket thread never calls into Mumble; a second thread makes the calls for
the mute, which Mumble runs in its main thread (see the comment at the top of `plugin.c`). It connects again every
2 seconds while the daemon is not there, so the order in which Mumble and the daemon start does not matter. `$XTOUCH_DAEMON_VOIP_SOCKET` (in Mumble's environment) points it to
another socket.

## Building it

```shell
cmake -S integrations/mumble -B integrations/mumble/build
cmake --build integrations/mumble/build
```

makes `libxtouch-daemon.so` and the bundle `xtouch-daemon.mumble_plugin` (the library and a `manifest.xml`, as Mumble
installs plugins), the same as `xtouch-daemon mumble-plugin --build`. The releases have it built in
`/usr/share/xtouch-daemon/`, CI builds it on every push. The plugin header `integrations/mumble/include/MumblePlugin.h`
is Mumble's (from Mumble 1.5.939, BSD-3-Clause, see `include/LICENSE.mumble`).
