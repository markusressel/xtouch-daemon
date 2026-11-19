"""
The pages of the documentation link the words of the project to where they are explained, as Wikipedia does: a page
that uses a word (a slot, an encoder, Home Assistant) at least `MENTIONS` times links to one of its pages at least
once, best at its first mention. Not every mention: that would be noise. docs/development is for developers and
links as it needs.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

DOCS = Path(__file__).parent.parent / "docs"
MENTIONS = 3
"""How often a page uses a word before it has to link it."""


@dataclass(frozen=True)
class Term:
    name: str
    pattern: str
    """A regular expression of its mentions (matched case-sensitively, outside code blocks, headings and links)."""
    homes: tuple[str, ...]
    """The pages that explain it (relative to docs/): a link to any of them counts."""
    not_on: tuple[str, ...] = ()
    """Pages where the word means something else (a channel of the voice chat)."""


TERMS = (
    Term("slot", r"\b[Ss]lots?\b", ("configuration/slots.md", "concepts.md")),
    Term("pool", r"\b[Pp]ools?\b", ("configuration/slots.md", "concepts.md")),
    Term("mode", r"\b[Mm]odes?\b(?! of)", ("configuration/slots.md", "concepts.md"), ("reference/hardware.md",)),
    Term("condition", r"\b[Cc]onditions?\b", ("configuration/slots.md", "concepts.md")),
    Term(
        "channel",
        r"\b[Cc]hannels?\b",
        ("configuration/channels/index.md", "concepts.md", "configuration/slots.md"),
        ("guides/mumble.md", "reference/voice-chat-bridge.md"),
    ),
    Term("encoder", r"\b[Ee]ncoders?\b", ("configuration/strip/encoders.md",)),
    Term("LED", r"\bLEDs?\b", ("configuration/strip/leds.md",)),
    Term("preset", r"\b[Pp]resets?\b|`@[a-z]+`", ("configuration/presets.md",)),
    Term("behavior", r"`\[behavior\]`|`behavior\.", ("configuration/behavior.md",)),
    Term("aliases", r"`\[aliases\]`|\b[Aa]lias(es)?\b", ("configuration/behavior.md",)),
    Term("Home Assistant", r"Home Assistant", ("guides/home-assistant.md",)),
    Term("Mumble", r"\bMumble\b", ("guides/mumble.md",)),
    Term("GUI", r"\bGUI\b", ("guides/gui.md",)),
    Term("virtual device", r"virtual device", ("getting-started/without-a-device.md",)),
    Term("commands", r"`xtouch-daemon [a-z-]+", ("reference/commands.md",)),
)

LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)\)")
"""A Markdown link; its text may hold brackets (`` [`[aliases]`](behavior.md#aliases) ``)."""


def pages() -> list[Path]:
    return sorted(page for page in DOCS.rglob("*.md") if DOCS / "development" not in page.parents)


def prose(text: str) -> str:
    """The text of a page without what never links: code blocks, headings and the text of links."""
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    text = re.sub(r"^#.*$", "", text, flags=re.M)
    return LINK.sub("", text)


def linked(page: Path, text: str) -> set[str]:
    """The pages `page` links to, relative to docs/ (itself for a link within it)."""
    targets: set[str] = set()
    for _, href in LINK.findall(text):
        if re.match(r"[a-z]+:", href):
            continue
        path = href.split("#")[0]
        target = (page.parent / path).resolve() if path else page.resolve()
        if target.is_relative_to(DOCS.resolve()):
            targets.add(target.relative_to(DOCS.resolve()).as_posix())
    return targets


@pytest.mark.parametrize("page", pages(), ids=lambda page: page.relative_to(DOCS).as_posix())
def test_a_page_links_the_words_it_uses(page: Path):
    name = page.relative_to(DOCS).as_posix()
    text = page.read_text()
    targets = linked(page, text)
    unlinked = [
        f"{term.name} ({count}×, link one of {', '.join(term.homes)})"
        for term in TERMS
        if name not in term.homes
        and name not in term.not_on
        and (count := len(re.findall(term.pattern, prose(text)))) >= MENTIONS
        and not targets & set(term.homes)
    ]
    assert not unlinked, f"{name} uses without a link: {'; '.join(unlinked)}"
