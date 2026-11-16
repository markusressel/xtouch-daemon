"""
`inherit` strips in the editor: the strip one refers to, for the preview, and the layouts and strips to pick from.
Like `Config` resolves them, from the values as typed; what can't be resolved is a problem of the validation.
"""

from typing import Any

from xtouch_daemon.config import DEFAULT_LAYOUT, INHERIT_LIMIT
from xtouch_daemon.gui.domain.document import ConfigDocument
from xtouch_daemon.gui.domain.sources import Suggestion

AUTO: dict[str, Any] = {"type": "auto"}


def _strips(document: ConfigDocument, layout: str) -> list[dict[str, Any]] | None:
    """The strips of the layout of the name, None for none."""
    if layout not in document.layout_names:
        return None
    index = document.layout_names.index(layout)
    drafts = document.default_strips if index == 0 else document.layouts[index - 1].strips
    return [strip.values for strip in drafts]


def _position(strips: list[dict[str, Any]], strip: object, position: int) -> int | None:
    """The position of the strip `strip` refers to (one from 1, or an `id`), `position` for none; None if none is."""
    if isinstance(strip, int) and not isinstance(strip, bool):
        return strip - 1 if 1 <= strip <= len(strips) else None
    if isinstance(strip, str):
        found = [index for index, values in enumerate(strips) if values.get("id") == strip]
        return found[0] if len(found) == 1 else None
    return position


def referenced(document: ConfigDocument, position: int) -> tuple[dict[str, Any], str] | None:
    """
    The strip the strip at `position` of the layout being edited is, through its `inherit` strips, and where it is
    (e.g. "layout voice, strip 3"), or None if it is no `inherit` strip or refers to none. Without `strip`, the strip
    at the same position (the daemon goes by places, which differ after a `voip` strip with more than one).
    """
    layout = document.layout_name
    strips = [strip.values for strip in document.strips]
    values = strips[position]
    if values.get("type") != "inherit":
        return None
    for _ in range(INHERIT_LIMIT):
        layout = str(values.get("layout") or DEFAULT_LAYOUT)
        target = _strips(document, layout)
        if target is None:
            return None
        same = values.get("strip") is None
        position_or_none = _position(target, values.get("strip"), position)
        if position_or_none is None:
            return None
        position = position_or_none
        if position >= len(target):
            # an auto strip after the configured ones, if it is at the same place
            return (AUTO, f"{_layout_name(layout)}, strip {position + 1}") if same else None
        values = target[position]
        if values.get("type") != "inherit":
            return values, f"{_layout_name(layout)}, strip {position + 1}"
    return None


def _layout_name(layout: str) -> str:
    return "the default layout" if layout == DEFAULT_LAYOUT else f"layout {layout}"


def layouts(document: ConfigDocument) -> tuple[Suggestion, ...]:
    """The layouts for `layout` of an `inherit` strip, with their labels."""
    result = [Suggestion(DEFAULT_LAYOUT, "the top-level strips")]
    for layout in document.layouts:
        name = layout.values.get("name")
        if isinstance(name, str) and name:
            result.append(Suggestion(name, str(layout.values.get("label") or "")))
    return tuple(result)


def strips(document: ConfigDocument, layout: object) -> tuple[Suggestion, ...]:
    """The strips of the layout (the default one for none) for `strip` of an `inherit` strip: positions and ids."""
    target = _strips(document, str(layout or DEFAULT_LAYOUT))
    if target is None:
        return ()
    result: list[Suggestion] = []
    for number, values in enumerate(target, start=1):
        what = " ".join(str(part) for part in (values.get("type", ""), values.get("label", "")) if part)
        result.append(Suggestion(str(number), what))
    ids = [values.get("id") for values in target]
    result.extend(
        Suggestion(strip_id, f"the strip with this id, {ids.index(strip_id) + 1}")
        for strip_id in ids
        if isinstance(strip_id, str) and ids.count(strip_id) == 1
    )
    return tuple(result)
