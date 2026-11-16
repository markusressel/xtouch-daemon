"""
The voice chat on the page of `[voip]`: whether the daemon has the participants, and setting up the Mumble plugin
(see `xtouch_daemon.mumble`).
"""

from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.status import Status, Tone
from xtouch_daemon.live import Snapshot
from xtouch_daemon.mumble import Setup


def voip_status(snapshot: Snapshot | None) -> Status:
    """Where the participants of the running daemon come from, and whether a plugin is connected."""
    if snapshot is None:
        return Status(
            "unknown",
            Tone.NEUTRAL,
            "The daemon does not run, or gives no live view: once it runs, this tells whether Mumble is connected.",
        )
    voip = snapshot.voip
    if voip is None:
        return Status(
            "not in use",
            Tone.WARN,
            "The daemon runs without voip strips or a [voip] section: add one and save, the daemon reloads.",
        )
    if voip.provider == "demo":
        return Status("demo", Tone.NEUTRAL, 'The participants are made up (provider = "demo"), Mumble is not asked.')
    if not voip.connected:
        return Status(
            "waiting for Mumble",
            Tone.WARN,
            "The daemon waits for the plugin: start Mumble, and enable the plugin xtouch-daemon in its settings.",
        )
    people = f"{voip.participants} {'person' if voip.participants == 1 else 'people'}"
    channel = f" in {voip.channel}" if voip.channel else ""
    client = (voip.client or "a client").capitalize()
    return Status(f"{client} connected", Tone.GOOD, f"{people}{channel}.")


def participants(snapshot: Snapshot | None) -> tuple[Suggestion, ...]:
    """The people in the voice chat now, for `person` of a `voip` strip."""
    if snapshot is None or snapshot.voip is None:
        return ()
    return tuple(Suggestion(name, "in the voice chat now") for name in snapshot.voip.names)


def people_on_strips(snapshot: Snapshot | None, count: int) -> tuple[str | None, ...]:
    """
    For each of `count` strips of the layout the snapshot shows, the participant on it: None for nobody, for the
    strips that are no `voip` strips, and for each of them without a live view.
    """
    strips = snapshot.voip.strips if snapshot is not None and snapshot.voip is not None else ()
    return tuple(strips[index] if index < len(strips) else None for index in range(count))


def install_hint(setup: Setup) -> str:
    """What "Install Mumble plugin" does, or why it can't."""
    if not setup.mumble:
        return "Mumble is not installed: install it first (e.g. the package mumble)."
    if setup.bundle is None and not setup.buildable:
        return "There is no plugin to install: a release has it, a checkout builds it with cmake and a C compiler."
    action = "Builds the plugin, then copies" if setup.bundle is None else "Copies"
    return f'{action} it into Mumble\'s plugin directory; then Mumble needs "Reload plugins".'


def install_steps(setup: Setup) -> list[str]:
    """The steps of the setup, as the window lists them."""
    installed = (
        f"Mumble has the plugin ({setup.installed})." if setup.installed is not None else "Mumble asks: confirm."
    )
    return [
        f'"Install Mumble plugin" below. {installed}',
        'In Mumble: Settings, Plugins, "Reload plugins" (or restart Mumble), tick Enable of "xtouch-daemon", Apply.',
        'Here: keep provider = "bridge", and give a layout voip strips (e.g. one used while Mumble runs).',
        "Join a channel: the people in it come onto the strips, the fader sets their volume, Mute mutes them.",
    ]
