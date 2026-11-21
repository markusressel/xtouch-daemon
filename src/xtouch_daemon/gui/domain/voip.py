"""
The voice chat on the page of `[voip]`: whether the daemon has the participants, and setting up the plugin of each
voice chat client (see `xtouch_daemon.voip.mumble` and `xtouch_daemon.voip.teamspeak`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.live.messages import Snapshot, VoipState
from xtouch_daemon.voip import mumble, teamspeak


@dataclass(frozen=True)
class PluginSetup:
    """What there is of the plugin of a client on this machine (`mumble.Setup`, `teamspeak.Setup`)."""

    plugin: Path | None
    """The plugin to install, if there is one."""
    buildable: bool
    """Whether the plugin can be built here (a checkout with CMake and a C compiler)."""
    installed: Path | None
    """The plugin in the client's plugin directory, if the client has it."""
    client: bool
    """Whether the client is installed."""

    @property
    def installable(self) -> bool:
        return self.client and (self.plugin is not None or self.buildable)


NO_PLUGIN = PluginSetup(None, False, None, False)
"""Neither the client nor a plugin."""


def mumble_setup() -> PluginSetup:
    found = mumble.setup()
    return PluginSetup(found.bundle, found.buildable, found.installed, found.mumble)


def teamspeak_setup() -> PluginSetup:
    found = teamspeak.setup()
    return PluginSetup(found.library, found.buildable, found.installed, found.teamspeak)


@dataclass(frozen=True)
class VoipClient:
    """A voice chat client with a plugin of xtouch-daemon, as the page of `[voip]` sets it up."""

    key: str
    """What its plugin sends as `client`, e.g. "mumble"."""
    name: str
    package: str
    """The package that installs the client, for the hint without it."""
    target: str
    """Where the install puts the plugin."""
    reload: str
    """What the client needs after the install, e.g. `"Reload plugins"`."""
    enable: str
    """The step in the client that loads and enables the plugin."""
    guide: str
    """The page of the guide (`docs.guide_link()`)."""
    setup: Callable[[], PluginSetup]
    install: Callable[[], str]


MUMBLE = VoipClient(
    key="mumble",
    name="Mumble",
    package="mumble",
    target="Mumble's plugin directory",
    reload='"Reload plugins"',
    enable='In Mumble: Settings, Plugins, "Reload plugins" (or restart Mumble), tick Enable of "xtouch-daemon", Apply.',
    guide="mumble",
    setup=mumble_setup,
    install=mumble.install,
)
TEAMSPEAK = VoipClient(
    key="teamspeak",
    name="TeamSpeak",
    package="teamspeak3",
    target="~/.ts3client/plugins",
    reload='"Reload All" in Tools, Options, Addons',
    enable='In TeamSpeak: Tools, Options, Addons, "Reload All" (or restart TeamSpeak), enable "xtouch-daemon", OK.',
    guide="teamspeak",
    setup=teamspeak_setup,
    install=teamspeak.install,
)
CLIENTS = (MUMBLE, TEAMSPEAK)
"""The clients with a plugin, in the order of their boxes."""
CLIENT_NAMES = {client.key: client.name for client in CLIENTS}
"""How the clients of the plugins write their names (the plugins send them in lowercase)."""


def client_names(voip: VoipState) -> list[str]:
    """The clients whose plugins are connected: `client` names one, or several joined with commas."""
    if not voip.connected:
        return []
    return [name.strip().lower() for name in (voip.client or "").split(",") if name.strip()]


def display_name(key: str) -> str:
    return CLIENT_NAMES.get(key) or key.capitalize()


def _people(voip: VoipState) -> str:
    people = f"{voip.participants} {'person' if voip.participants == 1 else 'people'}"
    return f"{people} in {voip.channel}." if voip.channel else f"{people}."


def voip_status(snapshot: Snapshot | None, client: VoipClient) -> Status:
    """Where the participants of the running daemon come from, and whether the plugin of `client` is connected."""
    if snapshot is None:
        return Status(
            "unknown",
            Tone.NEUTRAL,
            f"The daemon does not run, or gives no live view: once it runs, this tells whether {client.name} is "
            "connected.",
        )
    voip = snapshot.voip
    if voip is None:
        return Status(
            "not in use",
            Tone.WARN,
            "The daemon runs without a [voip] section: add one and save, the daemon reloads.",
        )
    if voip.provider == "demo":
        return Status(
            "demo", Tone.NEUTRAL, f'The participants are made up (provider = "demo"), {client.name} is not asked.'
        )
    connected = client_names(voip)
    if client.key in connected:
        return Status(f"{client.name} connected", Tone.GOOD, _people(voip))
    if voip.connected:
        other = ", ".join(display_name(key) for key in connected) or "another client"
        return Status(
            "not connected",
            Tone.NEUTRAL,
            f"The plugin of {other} is connected: {_people(voip)} The daemon takes one plugin per client.",
        )
    return Status(
        f"waiting for {client.name}",
        Tone.WARN,
        f"The daemon waits for the plugin: start {client.name}, and enable the plugin xtouch-daemon in its settings.",
    )


def connected_here(snapshot: Snapshot | None, client: VoipClient) -> bool:
    """Whether the plugin of `client` is connected to the running daemon."""
    voip = snapshot.voip if snapshot is not None else None
    return voip is not None and client.key in client_names(voip)


def participants(snapshot: Snapshot | None) -> tuple[Suggestion, ...]:
    """The people in the voice chat now, for `person` of a `voip` strip."""
    if snapshot is None or snapshot.voip is None:
        return ()
    return tuple(Suggestion(name, "in the voice chat now") for name in snapshot.voip.names)


def install_hint(client: VoipClient, setup: PluginSetup) -> str:
    """What "Install ... plugin" does, or why it can't."""
    if not setup.client:
        return f"{client.name} is not installed: install it first (e.g. the package {client.package})."
    if setup.plugin is None and not setup.buildable:
        return "There is no plugin to install: a release has it, a checkout builds it with cmake and a C compiler."
    action = "Builds the plugin, then copies" if setup.plugin is None else "Copies"
    return f"{action} it into {client.target}; then {client.name} needs {client.reload}."


def install_steps(client: VoipClient, setup: PluginSetup) -> list[str]:
    """The steps of the setup, as the window lists them."""
    installed = (
        f"{client.name} has the plugin ({setup.installed})."
        if setup.installed is not None
        else f"It goes into {client.target}."
    )
    return [
        f'"Install {client.name} plugin" below. {installed}',
        client.enable,
        'Here: keep provider = "bridge"; the people share the `auto` slots, or get `person` channels of their own.',
        "Join a channel: the people in it come onto the strips, the fader sets their volume, Mute mutes them.",
    ]
