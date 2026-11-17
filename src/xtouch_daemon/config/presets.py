"""
Presets: named groups of applications for the lists that match applications by name, e.g. `@browsers` in `match`
instead of the names of every browser. See docs/design/presets.md.

A preset stands for parts of names like the ones users write, matched the same way (anywhere in the name, ignoring
case). The configuration expands presets when it is validated, so the rest of the daemon sees plain names only.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

PREFIX = "@"
"""What starts the name of a preset in a list, e.g. `@browsers`."""


class Kind(StrEnum):
    """What a list of names is matched against."""

    STREAMS = "streams"
    """The application name (`application.name`) and binary (`application.process.binary`) of an audio stream."""
    PROCESSES = "processes"
    """The names of the processes that run: their `comm` and the file name of their program."""


WHERE: dict[Kind, str] = {
    Kind.STREAMS: "`match` of apps strips, `apps` of layouts and `behavior.ignore`",
    Kind.PROCESSES: "`processes` of layouts",
}
"""The lists of each kind, for people."""


@dataclass(frozen=True)
class Preset:
    """A named group of applications, with the parts of their names for each kind of list it can be used in."""

    name: str
    """Without the `@`, e.g. "browsers"."""
    description: str
    streams: tuple[str, ...] | None = None
    """Parts of the names and binaries of the applications' streams; None: not for lists of streams."""
    processes: tuple[str, ...] | None = None
    """Parts of the names of the applications' processes; None: not for lists of processes."""
    note: str = ""
    """What to know before using it, e.g. what else it matches."""

    @property
    def entry(self) -> str:
        """How it is written in a list, e.g. `@browsers`."""
        return PREFIX + self.name

    def names(self, kind: Kind) -> tuple[str, ...] | None:
        """What it stands for in a list of the kind, None if it can't be used there."""
        return self.streams if kind == Kind.STREAMS else self.processes

    @property
    def kinds(self) -> tuple[Kind, ...]:
        return tuple(kind for kind in Kind if self.names(kind) is not None)


_WINE_STREAMS = ("steam_app_", ".exe", "wine-preloader", "wine64-preloader")
"""
The streams of games under Wine and Proton: their application name is the file name of the game (e.g. "Planet
Crafter.exe"), their binary Wine's preloader; some have `steam_app_` and the id of the game in their name.
"""

PRESETS: dict[str, Preset] = {
    preset.name: preset
    for preset in (
        Preset(
            "browsers",
            "Web browsers",
            streams=(
                "firefox",
                "librewolf",
                "floorp",
                "waterfox",
                "zen-bin",
                "chromium",
                "chrome",
                "brave",
                "vivaldi",
                "opera",
                "msedge",
                "epiphany",
                "falkon",
            ),
            processes=(
                "firefox",
                "librewolf",
                "floorp",
                "waterfox",
                "zen-bin",
                "chromium",
                "brave",
                "vivaldi",
                "opera",
                "msedge",
                "epiphany",
                "falkon",
            ),
            note="Electron applications before Electron 40 (e.g. the sounds of Discord) name their streams "
            '"Chromium" too. The processes leave out Google Chrome: its process `chrome` is also part of the name '
            "of the crash handler of every Electron application.",
        ),
        Preset(
            "voip",
            "Voice and video chats",
            streams=(
                "discord",
                "vesktop",
                "webrtc voiceengine",
                "mumble",
                "teamspeak",
                "ts3client",
                "signal",
                "element-desktop",
                "zoom",
                "slack",
                "telegram",
                "jitsi",
                "teams-for-linux",
            ),
            processes=(
                "discord",
                "vesktop",
                "mumble",
                "teamspeak",
                "ts3client",
                "signal",
                "element-desktop",
                "zoom",
                "slack",
                "telegram",
                "jitsi",
                "teams-for-linux",
            ),
            note='Discord talks in a stream of its own, "WEBRTC VoiceEngine".',
        ),
        Preset(
            "steam-games",
            "Games started from Steam",
            streams=_WINE_STREAMS,
            processes=("reaper",),
            note="Steam starts every game through its `reaper`, which runs as long as the game (not the install "
            "scripts it runs through it after an update). A stream does not tell who started a game: the streams are "
            "those of every game under Wine or Proton. The digital audio workstation REAPER is called `reaper` too: "
            "with it, name the games in `processes` instead.",
        ),
        Preset(
            "games",
            "Games: from Steam, and any under Wine or Proton (e.g. Lutris, Heroic)",
            streams=_WINE_STREAMS,
            processes=("reaper", "wineserver"),
            note="Lutris and Heroic leave no process of their own while a game runs; `wineserver` runs while any "
            "Windows program runs under Wine or Proton, and a few seconds after it. Native games from Lutris or "
            "Heroic are not part of it.",
        ),
        Preset(
            "music",
            "Music players",
            streams=(
                "spotify",
                "rhythmbox",
                "strawberry",
                "clementine",
                "elisa",
                "lollypop",
                "amberol",
                "audacious",
                "deadbeef",
                "quod libet",
                "quodlibet",
                "cmus",
                "music player daemon",
            ),
            processes=(
                "spotify",
                "rhythmbox",
                "strawberry",
                "clementine",
                "elisa",
                "lollypop",
                "amberol",
                "audacious",
                "deadbeef",
                "quodlibet",
                "cmus",
                "mpd",
            ),
        ),
        Preset(
            "video",
            "Video players",
            streams=("vlc", "mpv", "celluloid", "totem", "kodi", "haruna", "clapper", "mplayer"),
            processes=("vlc", "mpv", "celluloid", "totem", "kodi", "haruna", "clapper", "mplayer"),
        ),
    )
}
"""Every preset, by name."""


def is_preset(entry: str) -> bool:
    return entry.startswith(PREFIX)


def preset_of(entry: str, presets: Mapping[str, Preset] | None = None) -> Preset | None:
    """The preset of an entry like `@browsers`, None for a plain name or an unknown preset."""
    return (presets or PRESETS).get(entry.removeprefix(PREFIX)) if is_preset(entry) else None


def known(presets: Mapping[str, Preset] | None = None) -> str:
    return ", ".join(preset.entry for preset in (presets or PRESETS).values())


def expand(entries: Iterable[str], kind: Kind, presets: Mapping[str, Preset] | None = None) -> tuple[str, ...]:
    """
    The entries of a list of the kind with the presets replaced by what they stand for, without duplicates.
    ValueError for an unknown preset, or one that can't be used in a list of the kind.
    """
    presets = presets or PRESETS
    result: dict[str, None] = {}
    for entry in entries:
        if not is_preset(entry):
            result[entry] = None
            continue
        preset = preset_of(entry, presets)
        if preset is None:
            raise ValueError(f"{entry} is no preset; the presets are {known(presets)}")
        names = preset.names(kind)
        if names is None:
            where = " and ".join(WHERE[other] for other in preset.kinds)
            raise ValueError(f"{entry} is not for {WHERE[kind]}; use it in {where}")
        result.update(dict.fromkeys(names))
    return tuple(result)


def expand_known(entries: Iterable[str], kind: Kind, presets: Mapping[str, Preset] | None = None) -> tuple[str, ...]:
    """
    Like `expand()`, but a preset that can't be used in a list of the kind (or is unknown) stands for nothing: the
    processes of the entries of a list of streams, e.g. to tell whether a silent application of an `apps` strip runs.
    """
    presets = presets or PRESETS
    usable = [
        entry
        for entry in entries
        if not is_preset(entry) or ((preset := preset_of(entry, presets)) is not None and kind in preset.kinds)
    ]
    return expand(usable, kind, presets)


def describe(entries: Iterable[str], kind: Kind) -> str:
    """The entries for people, presets with what they stand for, e.g. "@video (vlc, mpv, ...), kodi"."""
    parts: list[str] = []
    for entry in entries:
        preset = preset_of(entry)
        names = preset.names(kind) if preset is not None else None
        parts.append(f"{entry} ({', '.join(names)})" if names is not None else entry)
    return ", ".join(parts)


def matching_stream(app: str, binary: str) -> tuple[str, ...]:
    """The presets whose streams match an application, e.g. `("@browsers",)` for Brave."""
    values = [value.lower() for value in (app, binary) if value]
    return tuple(
        preset.entry
        for preset in PRESETS.values()
        if any(part in value for part in preset.streams or () for value in values)
    )


def markdown_table() -> str:
    """
    The presets as the table of docs/configuration/presets.md, and what to know about them below it (a test keeps the
    page in line with it).
    """
    lines = ["| Preset | What | Streams (`match`, `apps`, `ignore`) | Processes (`processes`) |", "|---|---|---|---|"]
    for preset in PRESETS.values():
        cells = [
            ", ".join(f"`{name}`" for name in names) if names is not None else "-"
            for names in (preset.streams, preset.processes)
        ]
        lines.append(f"| `{preset.entry}` | {preset.description} | {cells[0]} | {cells[1]} |")
    notes = [f"- `{preset.entry}`: {preset.note}" for preset in PRESETS.values() if preset.note]
    return "\n".join([*lines, *(["", *notes] if notes else [])])
