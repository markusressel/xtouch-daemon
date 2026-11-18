# Design: presets

Status: built. How to use it: [Presets](../../configuration/presets.md).

The idea: common groups of applications (every browser, every voice chat, every game started from Steam) get a name,
so nobody has to look up what each application calls its streams and processes. `match = ["@browsers"]` instead of
`match = ["brave", "firefox", "chromium", ...]`.

## Where applications are matched by name

| Where | Matched against | Kind |
|---|---|---|
| `match` of `apps` channels | the application name (`application.name`) and binary (`application.process.binary`) of each stream | streams |
| `apps` and `recording` of states | the same | streams |
| `exclude` of `[pool.apps]` (what `apps` and `auto` never take) | the same | streams |
| `processes` of states | the names of the processes (`comm`, and the file name of the program) | processes |
| "runs" of an `apps` channel with `launch` | the processes, with the `match` entries | processes |
| the program of `launch` | the processes, the file name of the program exactly | none: a command, not a list of names |
| `person` of `person` channels, `[aliases]` | names of people, exact names of applications | none |

Presets go where the user writes a list of parts of names: the first four rows. The fifth follows from `match`.

## How a preset is written

- `@name` in the list, next to plain names: `match = ["@voip", "my-voice-app"]`. An `@` never starts the name of an
  application or process in practice, and TOML needs no quoting beyond the string. A separate option
  (`match_presets = [...]`) was the alternative; one list is shorter and works the same in every list.
- Names are lower case with hyphens: `@steam-games`.

## What a preset stands for

`presets.py` holds the table: each `Preset` has a description, the names for lists of streams (`streams`) and for
lists of processes (`processes`), either of which may be `None` (not for that kind of list), and a note for the docs.

- **The names are matched like the user's**: as parts of the name, ignoring case. A preset is nothing but a list of
  names, so it can't do anything the user could not write, and `list-apps` and `check-config` explain it in the same
  terms. Exact matching or regular expressions would be a second matching mode for little gain.
- **A preset stands for different names in each kind of list.** Streams and processes are named differently: a Proton
  game plays as `Planet Crafter.exe` (binary `wine64-preloader`), but its processes are Wine's, and `.exe` in a list
  of processes matches Wine's helpers (`explorer.exe`, `services.exe`) and Proton's `steam.exe`. Steam starts every
  game through its `reaper`, which is the reliable process, and has no stream.
- **Errors at validation.** An unknown preset lists the known ones. A preset in a list it has no names for says
  where it can be used. Both are pydantic errors of the option, so `check-config` and the GUI show them at their
  place (`channel.browser.match: ...`).

## Expanded when the configuration is validated

The models expand presets in a validator of the list's type (`StreamNames` in `config/names.py`, `Streams` and
`Processes` in `slots/model.py`), so the strips, the states, the pools and `list-apps` see plain names. The
`Presets` metadata of the type marks the option for the GUI's schema.

The entries as written stay on the model (`_WithPresets.written()`, a private attribute filled by a wrap validator),
for what explains the configuration to people: `check-config` shows `@browsers (firefox, librewolf, ...)`. The GUI
edits the TOML document itself, not the models, so it always shows `@browsers` and writes it back as it was.

An `apps` channel with `launch` counts its applications as running when a process of theirs runs: before presets, the
`match` entries were matched against the processes as they are. Now the plain entries still are, and each preset
counts with its names for processes (`AppsStripConfig.process_names`), so `@steam-games` counts `reaper`, not `.exe`.

## The presets

Each is a short list of well-known applications, checked against what they report on a real system where possible
(Brave, Mumble and a Proton game on this machine) and against their packages otherwise. Choices:

- **No broad names.** `steam` (the client runs all the time), `.exe` in processes, `chrome` in processes (every
  Electron application runs a `chrome_crashpad_handler`), `element` (elementary OS's `io.elementary.*`), bare `zen`,
  `jellyfin` (the server is a process too), `dragon` (games). Tests list such names for each preset and fail if one
  matches them.
- **Streams can't tell who started a game.** A Proton game from Steam and a Wine game from Lutris play alike, so the
  streams of `@steam-games` and `@games` are the same: every Windows program under Wine.
- **`@games` processes: `reaper` and `wineserver`.** Lutris and Heroic leave no process of their own while a game
  runs (Lutris's `lutris-wrapper` names itself only with an optional Python module), so there is no reliable marker
  for them. `wineserver` runs while any Windows program runs under Wine or Proton, which on a desktop is mostly games,
  and a few seconds after it (which the `delay_off` of a mode covers anyway). Native games from Lutris or Heroic are not part of
  it.
- **Electron.** Before Electron 40 every Electron application names its streams "Chromium" (with its own binary), so
  `chromium` in `@browsers` also takes their sounds, e.g. Discord's notifications. Leaving Chromium out of a browser
  preset would be worse; the docs say it.
- **REAPER.** The digital audio workstation's process is `reaper` too, so `@steam-games` in `processes` also
  matches while it runs. Its users name their games in `processes` instead; the note of the preset says so.

The docs page lists every preset with its names; a test checks that its table is `presets.markdown_table()`, so it
can't go stale.

## Where presets show

- `check-config`: each preset with what it stands for, in channels and states.
- `list-apps`: the presets each application that plays is part of (`Brave (@browsers)`), to find the right one.
- The GUI: the options with the `Presets` metadata suggest the presets of their kind first (a "Presets" section of
  the menu, the description beside each, what it stands for as the tooltip), then the names of the sound server; a
  `processes` list, which had no suggestions, gets the presets for processes. The chip of a preset is outlined instead
  of filled and has the same tooltip.
