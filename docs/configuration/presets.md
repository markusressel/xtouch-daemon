# Presets

A preset is a name for a group of well-known applications, so you don't have to look up the names of every browser
or the way games show up. Write it with an `@` in the lists that match applications, alone or next to names of your
own:

```toml
[channel.browser]
type = "apps"
label = "Browser"
match = ["@browsers"]

[channel.voip]
type = "apps"
label = "VoIP"
match = ["@voip", "my-voice-app"]

[state.gaming]
mode = true
processes = ["@steam-games"]    # while any game from Steam runs
```

Presets work in:

- `match` of [`apps` channels](channels/applications.md#apps-channels), `apps` of [states](slots.md#states-and-modes) and
  `exclude` of [`[pool.apps]`](channels/applications.md#apps-and-auto): they match the names and binaries of the applications' streams.
- `processes` of [states](slots.md#states-and-modes): they match the names of processes.

A preset stands for different names in each: e.g. `@steam-games` is the streams of Windows games (`.exe`) in
`match`, and Steam's `reaper` process in `processes`. Its names match like the ones you write, as parts of the
name, ignoring case. On an `apps` channel with `launch`, the processes of its presets count as the application
running. An unknown preset is an error that lists the known ones; a preset that can't be used in a list says where it
can.

`xtouch-daemon check-config` shows what each preset stands for, `xtouch-daemon list-apps` the presets of the
applications that play, and the [GUI](../guides/gui.md) suggests the presets that fit each list.

## The presets

<!-- presets: start -->
| Preset | What | Streams (`match`, `apps`, `exclude`) | Processes (`processes`) |
|---|---|---|---|
| `@browsers` | Web browsers | `firefox`, `librewolf`, `floorp`, `waterfox`, `zen-bin`, `chromium`, `chrome`, `brave`, `vivaldi`, `opera`, `msedge`, `epiphany`, `falkon` | `firefox`, `librewolf`, `floorp`, `waterfox`, `zen-bin`, `chromium`, `brave`, `vivaldi`, `opera`, `msedge`, `epiphany`, `falkon` |
| `@voip` | Voice and video chats | `discord`, `vesktop`, `webrtc voiceengine`, `mumble`, `teamspeak`, `ts3client`, `signal`, `element-desktop`, `zoom`, `slack`, `telegram`, `jitsi`, `teams-for-linux` | `discord`, `vesktop`, `mumble`, `teamspeak`, `ts3client`, `signal`, `element-desktop`, `zoom`, `slack`, `telegram`, `jitsi`, `teams-for-linux` |
| `@steam-games` | Games started from Steam | `steam_app_`, `.exe`, `wine-preloader`, `wine64-preloader` | `reaper` |
| `@games` | Games: from Steam, and any under Wine or Proton (e.g. Lutris, Heroic) | `steam_app_`, `.exe`, `wine-preloader`, `wine64-preloader` | `reaper`, `wineserver` |
| `@music` | Music players | `spotify`, `rhythmbox`, `strawberry`, `clementine`, `elisa`, `lollypop`, `amberol`, `audacious`, `deadbeef`, `quod libet`, `quodlibet`, `cmus`, `music player daemon` | `spotify`, `rhythmbox`, `strawberry`, `clementine`, `elisa`, `lollypop`, `amberol`, `audacious`, `deadbeef`, `quodlibet`, `cmus`, `mpd` |
| `@video` | Video players | `vlc`, `mpv`, `celluloid`, `totem`, `kodi`, `haruna`, `clapper`, `mplayer` | `vlc`, `mpv`, `celluloid`, `totem`, `kodi`, `haruna`, `clapper`, `mplayer` |

- `@browsers`: Electron applications before Electron 40 (e.g. the sounds of Discord) name their streams "Chromium" too. The processes leave out Google Chrome: its process `chrome` is also part of the name of the crash handler of every Electron application.
- `@voip`: Discord talks in a stream of its own, "WEBRTC VoiceEngine".
- `@steam-games`: Steam starts every game through its `reaper`, which runs as long as the game (not the install scripts it runs through it after an update). A stream does not tell who started a game: the streams are those of every game under Wine or Proton. The digital audio workstation REAPER is called `reaper` too: with it, name the games in `processes` instead.
- `@games`: Lutris and Heroic leave no process of their own while a game runs; `wineserver` runs while any Windows program runs under Wine or Proton, and a few seconds after it. Native games from Lutris or Heroic are not part of it.
<!-- presets: end -->

Missing an application? Add its name next to the preset (`match = ["@browsers", "netsurf"]`), and open an issue,
so the preset gets it.

Next: [Applications](channels/applications.md) uses them in `match`.
