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
    """
    The anchors of the headings of a page: its own (`## Title { #anchor }`), or else from the title; a heading that is
    there already gets `_1`, `_2`, ...
    """
    result: set[str] = set()
    fenced = False
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (explicit := re.match(r"#{1,6} .+\{ *#([\w-]+) *\}\s*$", line)):
            result.add(explicit[1])
        elif not fenced and (heading := re.match(r"#{1,6} (.+)", line)):
            anchor = base = slug(heading[1])
            number = 0
            while anchor in result:
                number += 1
                anchor = f"{base}_{number}"
            result.add(anchor)
    return result


def source(path: str) -> Path:
    """
    The Markdown file of a page of the site: `configuration/behavior/` is `configuration/behavior.md`,
    `configuration/channels/` the index of its folder, `configuration/channels/index.md`.
    """
    page = path.strip("/")
    if not page:
        return DOCS / "index.md"
    file = DOCS / f"{page}.md"
    return file if file.is_file() else DOCS / page / "index.md"


def test_the_anchors_are_those_of_the_site(tmp_path: Path):
    assert slug("100 % at the 0 dB mark") == "100-at-the-0-db-mark"
    assert slug('`fader = "homeassistant"`') == "fader-homeassistant"
    assert slug("`[mqtt]`") == "mqtt"
    assert slug("Devices: `output` and `input` strips") == "devices-output-and-input-strips"
    page = tmp_path / "page.md"
    page.write_text("## The service\n\n## The service\n")
    assert anchors(page) == {"the-service", "the-service_1"}
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
    assert set(docs.PAGES) == {
        "device",
        "behavior",
        "aliases",
        "mqtt",
        "homeassistant",
        "channels",
        "states",
        "switching",
        "voip",
    }
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
    assert (
        docs.page_link("mqtt")
        == f"https://markusressel.github.io/xtouch-daemon/{docs.DOCS_VERSION}/guides/home-assistant/#mqtt"
    )
    assert docs.page_link("strips") is None
    assert docs.option_link("strip", "rec", "input") == docs.url("configuration/strip/leds/#buttons")
    # a type may link an option elsewhere
    assert docs.option_link("strip", "label", "voip") == docs.url(
        "configuration/channels/people/#strips-for-one-person"
    )
    assert docs.option_link("strip", "meter", "output") is None
    # bindings, and the options of custom channels
    assert docs.option_link("strip", "lcd", "output", bound=True) == docs.url("configuration/strip/bindings/")
    assert docs.option_link("strip", "color", "output", bound=True) == docs.url("configuration/strip/bindings/")
    # the color of a person can't be bound: no page of bindings for it
    assert docs.option_link("strip", "color", "voip") is None
    assert docs.option_link("strip", "meter", "custom") == docs.url("configuration/strip/bindings/")
    assert docs.option_link("strip", "fader", "custom") == docs.url("configuration/channels/custom/#a-value")
    assert docs.option_link("behavior", "unity_at") == docs.url("configuration/channels/#100-at-the-0-db-mark")
    assert docs.option_link("behavior", "meters") is None
    assert docs.option_link("aliases", "anything") is None
