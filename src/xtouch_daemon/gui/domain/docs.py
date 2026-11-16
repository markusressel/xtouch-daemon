"""
Where the documentation explains a page, a strip type or an option: the "Learn more" links of the editor. The paths
are those of the site built from `docs/` (`configuration/strips.md` is `configuration/strips/`), the anchors those of
its headings; a test checks that they exist.
"""

DOCS_URL = "https://markusressel.github.io/xtouch-daemon/"
"""The documentation site."""

PAGES: dict[str, str] = {
    "device": "configuration/behavior/#device",
    "behavior": "configuration/behavior/#behavior",
    "aliases": "configuration/behavior/#aliases",
    "mqtt": "home-assistant/#mqtt",
    "layout": "configuration/layouts/",
    "switching": "configuration/layouts/#switching",
    "voip": "configuration/layouts/#voice-chat",
}
"""The global settings, by page."""

GUIDES: dict[str, str] = {
    "mumble": "integrations/mumble/",
}
"""The pages on setting up something outside the daemon, e.g. the plugin of a voice chat client."""

STRIP_TYPES: dict[str, str] = {
    "output": "configuration/devices/",
    "input": "configuration/devices/",
    "apps": "configuration/applications/#apps-strips",
    "auto": "configuration/applications/#auto-strips",
    "homeassistant": "home-assistant/#homeassistant-strips",
    "empty": "configuration/strips/#empty-strips",
    "inherit": "configuration/layouts/#inherit-strips",
    "voip": "configuration/layouts/#voip-strips",
}
"""The strip types."""

STRIP_OPTIONS: dict[str, str] = {
    "rec": "configuration/indicators/#indicators",
    "solo": "configuration/indicators/#indicators",
    "min_volume": "configuration/strips/#volume-range",
    "max_volume": "configuration/strips/#volume-range",
    "encoder": "configuration/encoders/",
    "fader": "configuration/encoders/#fader-homeassistant",
    "id": "home-assistant/#audio-strips-with-home-assistant-controls",
    "label": "configuration/strips/#labels",
    "device": "configuration/devices/#several-devices",
    "profiles": "configuration/devices/#profiles",
    "choices": "configuration/devices/#choices",
    "collapse": "configuration/collapsing/",
    "match": "configuration/applications/#apps-strips",
    "launch": "configuration/applications/#launching-the-application",
    "launch_when_running": "configuration/applications/#launching-the-application",
    "person": "configuration/layouts/#strips-for-one-person",
}
"""The options of the strips; `STRIP_TYPE_OPTIONS` overrides them for one type."""

STRIP_TYPE_OPTIONS: dict[tuple[str, str], str] = {
    ("homeassistant", "id"): "home-assistant/#entities",
    ("voip", "label"): "configuration/layouts/#strips-for-one-person",
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
        "auto_hold": "configuration/applications/#auto-strips",
        "ignore": "configuration/applications/#auto-strips",
        "collapse_hold": "configuration/collapsing/#when-a-strip-has-nothing-to-control",
    },
    "mqtt": {
        "namespace": "home-assistant/#entities",
    },
    "layout": {
        "apps": "configuration/layouts/#rules",
        "processes": "configuration/layouts/#rules",
        "priority": "configuration/layouts/#rules",
    },
    "switching": {
        "chord": "configuration/layouts/#switching",
        "hold": "configuration/layouts/#rules",
    },
}
"""The options of the sections, by section."""


def url(path: str) -> str:
    """The address of a page of the documentation, e.g. `configuration/strips/#labels`."""
    return DOCS_URL + path


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
