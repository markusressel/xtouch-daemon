"""
Where the documentation explains a page, a strip type or an option: the "Learn more" links of the editor. The paths
are those of the site built from `docs/` (`configuration/strips.md` is `configuration/strips/`), the anchors those of
its headings; a test checks that they exist.
"""

from xtouch_daemon import __version__

DOCS_URL = "https://markusressel.github.io/xtouch-daemon/"
"""The documentation site: its root shows the latest release (dev before the first one)."""
DOCS_VERSION = __version__
"""
The version of the documentation the links open: the one of this program. Before it is deployed (a checkout between
releases), the site forwards to the same page of the latest release (see `pages/404.html`).
"""

PAGES: dict[str, str] = {
    "device": "configuration/behavior/#device",
    "behavior": "configuration/behavior/#behavior",
    "aliases": "configuration/behavior/#aliases",
    "mqtt": "home-assistant/#mqtt",
    "channels": "configuration/slots/#channels",
    "states": "configuration/slots/#states-and-modes",
    "switching": "configuration/slots/#controls-and-the-chord",
    "voip": "configuration/people/#voice-chat",
}
"""The pages, and the settings by page."""

GUIDES: dict[str, str] = {
    "mumble": "integrations/mumble/",
    "slots": "configuration/slots/#slots",
    "conditions": "configuration/slots/#conditions",
}
"""
Pages on a topic the editor links to: setting up something outside the daemon (the plugin of a voice chat client),
the slots and their conditions.
"""

STRIP_TYPES: dict[str, str] = {
    "output": "configuration/devices/",
    "input": "configuration/devices/",
    "apps": "configuration/applications/#apps-channels",
    "auto": "configuration/applications/#apps-and-auto",
    "homeassistant": "home-assistant/#homeassistant-channels",
    "empty": "configuration/strips/#empty-slots",
    "voip": "configuration/people/",
}
"""The strip types."""

STRIP_OPTIONS: dict[str, str] = {
    "rec": "configuration/indicators/#indicators",
    "solo": "configuration/indicators/#indicators",
    "min_volume": "configuration/strips/#volume-range",
    "max_volume": "configuration/strips/#volume-range",
    "encoder": "configuration/encoders/",
    "fader": "configuration/encoders/#fader-homeassistant",
    "label": "configuration/strips/#labels",
    "device": "configuration/devices/#several-devices",
    "profiles": "configuration/devices/#profiles",
    "choices": "configuration/devices/#choices",
    "match": "configuration/applications/#apps-channels",
    "launch": "configuration/applications/#launching-the-application",
    "launch_when_running": "configuration/applications/#launching-the-application",
    "person": "configuration/people/#strips-for-one-person",
    "meter_point": "configuration/strips/#meters",
}
"""The options of the strips; `STRIP_TYPE_OPTIONS` overrides them for one type."""

STRIP_TYPE_OPTIONS: dict[tuple[str, str], str] = {
    ("voip", "label"): "configuration/people/#strips-for-one-person",
}

SECTION_OPTIONS: dict[str, dict[str, str]] = {
    "device": {
        "touch_required": "configuration/behavior/#faders-without-a-touch-sensor",
        "touchless_faders": "configuration/behavior/#faders-without-a-touch-sensor",
        "startup": "configuration/behavior/#startup-and-shutdown-sequences",
        "shutdown": "configuration/behavior/#startup-and-shutdown-sequences",
    },
    "behavior": {
        "max_volume": "configuration/strips/#100-at-the-0-db-mark",
        "unity_at": "configuration/strips/#100-at-the-0-db-mark",
        "encoder_step": "configuration/encoders/#volume",
        "reset_volume": "configuration/encoders/#volume",
        "meter_point": "configuration/strips/#meters",
    },
    "mqtt": {
        "namespace": "home-assistant/#entities",
    },
    "switching": {
        "chord": "configuration/slots/#controls-and-the-chord",
    },
}
"""The options of the sections, by section."""


def url(path: str) -> str:
    """The address of a page of the documentation, in the version of this program: e.g. `configuration/slots/`."""
    return f"{DOCS_URL}{DOCS_VERSION}/{path}"


def page_link(page: str) -> str | None:
    path = PAGES.get(page)
    return None if path is None else url(path)


def guide_link(guide: str) -> str:
    return url(GUIDES[guide])


def strip_type_link(strip_type: str) -> str | None:
    path = STRIP_TYPES.get(strip_type)
    return None if path is None else url(path)


def option_link(section: str, name: str, strip_type: str | None = None) -> str | None:
    """
    Where an option is explained: of a section (`behavior`), or of a strip (`section` "strip" with its type); None for
    an option that has no section of its own in the documentation (its help says it all).
    """
    if section == "strip":
        path = STRIP_TYPE_OPTIONS.get((str(strip_type), name)) or STRIP_OPTIONS.get(name)
    else:
        path = SECTION_OPTIONS.get(section, {}).get(name)
    return None if path is None else url(path)


def all_paths() -> list[str]:
    """Every path linked from the editor."""
    return [
        *PAGES.values(),
        *GUIDES.values(),
        *STRIP_TYPES.values(),
        *STRIP_OPTIONS.values(),
        *STRIP_TYPE_OPTIONS.values(),
        *(path for options in SECTION_OPTIONS.values() for path in options.values()),
    ]
