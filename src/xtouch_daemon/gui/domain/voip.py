"""
The voice chat on the page of `[voip]`: whether the daemon has the participants, and setting up the plugin of each
voice chat client (see `xtouch_daemon.voip.mumble` and `xtouch_daemon.voip.teamspeak`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.live.messages import Snapshot, VoipClient, VoipState
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
class ClientSetup:
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


MUMBLE = ClientSetup(
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
TEAMSPEAK = ClientSetup(
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
"""How the clients the GUI knows write their names; any other is capitalized."""


def _client_name(client: VoipClient) -> str:
    name = client.client or "a client"
    return CLIENT_NAMES.get(name, name.capitalize())


def connected_clients(voip: VoipState) -> tuple[VoipClient, ...]:
    """The clients whose plugins are connected (a daemon before `clients` tells one, in `client`)."""
    if not voip.connected:
        return ()
    return voip.clients or (VoipClient(voip.client or "a client", voip.channel),)


def voip_status(snapshot: Snapshot | None) -> Status:
    """Where the participants of the running daemon come from, and which plugins are connected."""
    if snapshot is None:
        return Status(
            "unknown",
            Tone.NEUTRAL,
            "The daemon does not run, or gives no live view: once it runs, this tells which plugins are connected.",
        )
    voip = snapshot.voip
    if voip is None:
        return Status(
            "not in use",
            Tone.WARN,
            "The daemon runs without a [voip] section: add one and save, the daemon reloads.",
        )
    if voip.provider == "demo":
        return Status("demo", Tone.NEUTRAL, 'The participants are made up (provider = "demo"), no client is asked.')
    if not voip.connected:
        return Status(
            "waiting for a plugin",
            Tone.WARN,
            "The daemon waits for a plugin: start Mumble or TeamSpeak, and enable the plugin xtouch-daemon in it.",
        )
    people = f"{voip.participants} {'person' if voip.participants == 1 else 'people'}"
    clients = connected_clients(voip)
    names = " and ".join(_client_name(client) for client in clients)
    if len(clients) == 1:
        channel = f" in {clients[0].channel}" if clients[0].channel else ""
        return Status(f"{names} connected", Tone.GOOD, f"{people}{channel}.")
    channels = ", ".join(
        f"{_client_name(client)} in {client.channel}" if client.channel else _client_name(client) for client in clients
    )
    return Status(f"{names} connected", Tone.GOOD, f"{people}: {channels}.")


def client_status(snapshot: Snapshot | None, client: ClientSetup) -> Status:
    """The pill of the box of `client`: whether its plugin is connected, with what the daemon has (`voip_status`)."""
    overall = voip_status(snapshot)
    voip = snapshot.voip if snapshot is not None else None
    if voip is None or voip.provider == "demo":
        return overall
    if not voip.connected:
        return Status(
            f"waiting for {client.name}",
            Tone.WARN,
            f"The daemon waits for the plugin: start {client.name}, and enable the plugin xtouch-daemon in its "
            "settings.",
        )
    if connected_here(snapshot, client):
        return Status(f"{client.name} connected", Tone.GOOD, overall.tip)
    return Status("not connected", Tone.NEUTRAL, f"{overall.text}: {overall.tip}")


def connected_here(snapshot: Snapshot | None, client: ClientSetup) -> bool:
    """Whether the plugin of `client` is connected to the running daemon."""
    voip = snapshot.voip if snapshot is not None else None
    return voip is not None and any(each.client == client.key for each in connected_clients(voip))


def participants(snapshot: Snapshot | None) -> tuple[Suggestion, ...]:
    """The people in the voice chat now, for `person` of a `voip` strip."""
    if snapshot is None or snapshot.voip is None:
        return ()
    return tuple(Suggestion(name, "in the voice chat now") for name in snapshot.voip.names)


def install_hint(client: ClientSetup, setup: PluginSetup) -> str:
    """What "Install ... plugin" does, or why it can't."""
    if not setup.client:
        return f"{client.name} is not installed: install it first (e.g. the package {client.package})."
    if setup.plugin is None and not setup.buildable:
        return "There is no plugin to install: a release has it, a checkout builds it with cmake and a C compiler."
    action = "Builds the plugin, then copies" if setup.plugin is None else "Copies"
    return f"{action} it into {client.target}; then {client.name} needs {client.reload}."


def install_steps(client: ClientSetup, setup: PluginSetup) -> list[str]:
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
