import re
import unicodedata
from pathlib import Path

import pytest

from tests.support.paths import DOCS
from xtouch_daemon.config.strips import STRIP_TYPES
from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.schema import options, sections, strip_models, strip_options


def slug(heading: str) -> str:
    """The anchor of a heading, like the table of contents of Python-Markdown (and so Zensical) makes it."""
    text = re.sub(r"\[([^]]*)]\([^)]*\)", r"\1", heading).replace("`", "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def anchors(page: Path) -> set[str]:
    """The anchors of the headings of a page; a heading that is there already gets `_1`, `_2`, ..."""
    result: set[str] = set()
    fenced = False
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (heading := re.match(r"#{1,6} (.+)", line)):
            anchor = base = slug(heading[1])
            number = 0
            while anchor in result:
                number += 1
                anchor = f"{base}_{number}"
            result.add(anchor)
    return result


def source(path: str) -> Path:
    """The Markdown file of a page of the site: `configuration/strips/` is `configuration/strips.md`."""
    page = path.strip("/")
    return DOCS / (f"{page}.md" if page else "index.md")


def test_the_anchors_are_those_of_the_site():
    assert slug("100 % at the 0 dB mark") == "100-at-the-0-db-mark"
    assert slug('`fader = "homeassistant"`') == "fader-homeassistant"
    assert slug("`[mqtt]`") == "mqtt"
    assert slug("Devices: `output` and `input` strips") == "devices-output-and-input-strips"
    gui = anchors(DOCS / "gui.md")
    assert {"the-service", "the-service_1"} <= gui
    # a comment in a code block is no heading
    assert "strips-7-and-8-are-not-configured-they-are-auto-strips" not in anchors(DOCS / "configuration/index.md")


@pytest.mark.parametrize("link", sorted(set(docs.all_paths())))
def test_every_link_goes_to_a_page_and_heading_of_the_docs(link: str):
    path, _, anchor = link.partition("#")
    page = source(path)
    assert page.is_file(), f"{link}: no {page.relative_to(DOCS.parent)}"
    if anchor:
        assert anchor in anchors(page), f"{link}: no heading with the anchor {anchor} in {page.name}"


def test_every_page_and_strip_type_has_its_docs():
    assert set(docs.PAGES) == {"device", "behavior", "aliases", "mqtt", "channels", "states", "switching", "voip"}
    assert set(docs.STRIP_TYPES) == set(STRIP_TYPES)


def test_the_linked_options_exist():
    strip_option_names = {o.name for strip_type in strip_models() for o in strip_options(strip_type)}
    assert set(docs.STRIP_OPTIONS) <= strip_option_names
    for strip_type, name in docs.STRIP_TYPE_OPTIONS:
        assert name in {o.name for o in strip_options(strip_type)}
    models = {section.name: section.model for section in sections()}
    for section, names in docs.SECTION_OPTIONS.items():
        assert set(names) <= {o.name for o in options(models[section])}


def test_links_are_addresses_on_the_site():
    assert docs.DOCS_URL == "https://markusressel.github.io/xtouch-daemon/"
    assert docs.page_link("mqtt") == "https://markusressel.github.io/xtouch-daemon/home-assistant/#mqtt"
    assert docs.page_link("strips") is None
    assert docs.strip_type_link("auto") == docs.url("configuration/channels/applications/#auto")
    assert docs.strip_type_link("pipewire") is None
    assert docs.option_link("strip", "rec", "input") == docs.url("configuration/strip/leds/#indicators")
    # a type may link an option elsewhere
    assert docs.option_link("strip", "label", "voip") == docs.url(
        "configuration/channels/people/#strips-for-one-person"
    )
    assert docs.option_link("strip", "meter", "output") is None
    assert docs.option_link("behavior", "unity_at") == docs.url("configuration/channels/#100-at-the-0-db-mark")
    assert docs.option_link("behavior", "meters") is None
    assert docs.option_link("aliases", "anything") is None
