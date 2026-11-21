# Presets

A preset is a name for a group of well-known applications, so you don't have to look up the names of every browser
or the way games show up. `@browsers` stands for Firefox, Chromium, Brave and the other browsers. The presets are
built in: you can't define your own, but you can add names of your own next to a preset, as below.

Write a preset with an `@` in the lists that match applications, alone or next to names of your own. These lines go
into the [configuration file](index.md). A channel shows on a strip only when a slot lists it (`4 = "browser"`),
see [Slots](slots.md#slots):

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

- Lists of streams: `match` of [`apps` channels](channels/applications.md#apps-channels), the source `apps` of a
  [state](slots.md#states-and-modes) (on while a matching application plays) and `exclude` of [`[pool.apps]`](channels/applications.md#apps-and-auto). A
  stream is the sound that one application plays. The preset matches the name of the application, or the name of its
  program file, that the sound server reports for the stream.
- Lists of processes: `processes` of [states](slots.md#states-and-modes). The preset matches the names of the programs
  that run on the computer.

One preset stands for different names in these two kinds of list. `@steam-games` is the streams of Windows games
(names that contain `.exe`) in `match`, and Steam's `reaper` process in `processes`. The table below has both columns.

The names of a preset match like the names you write: as a part of the name, ignoring upper and lower case. So the
name `signal` would also match `signal-desktop`.

An `apps` channel can have a `launch` command, which Select runs to start the application
([Launching the application](channels/applications.md#launching-the-application)). The channel then also counts as
running when a process of its presets runs, not only when a stream plays. While it counts as running, pressing Select does not
start the command again. Without this, a voice chat that is open but silent would have no stream, and Select would
start a second one.

An unknown preset is an error, and the message lists the known ones. A preset in a list where it makes no sense is
an error too, and the message says which lists accept it.

Three ways to see what presets do (all the commands are in [Commands](../reference/commands.md)):

- `xtouch-daemon check-config` shows what each preset in your file stands for.
- `xtouch-daemon list-apps` lists the applications that play right now. Next to each it names the presets that match
  it, and where it goes (a channel, `apps` or `auto`).
- The [GUI](../guides/gui.md) suggests the presets that fit each list.

## Surprises to know about

The notes under the table say why. In short, for what you will see:

- `@browsers` in `match` also catches the sounds of Electron applications older than Electron 40, e.g. Discord, which
  then play as "Chromium". Run `xtouch-daemon list-apps` to see where each application goes.
- `@browsers` in `processes` does not see Google Chrome. Add `chrome` yourself if you need it:
  `processes = ["@browsers", "chrome"]`.
- `@steam-games` in `match` also matches Windows games that Steam did not start, because a stream does not say who
  started the game. To match only games that Steam started, use it in `processes`.
- If you have the audio program REAPER, `@steam-games` in `processes` is on while REAPER runs. Name your games in
  `processes` instead.
- `@games` in `processes` also stays on for a few seconds after the game ends, because `wineserver` (a helper of Wine and Proton) keeps running. The delay of the state (`delay_off`) comes on top.

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

Missing an application? Add its name next to the preset (`match = ["@browsers", "netsurf"]`), and
[open an issue](https://github.com/markusressel/xtouch-daemon/issues), so the preset gets it. To match one specific
game instead of every Wine program, put the name of its process in `processes`:
`processes = ["mygame"]`.

Next: [Applications](channels/applications.md) uses them in `match`.
