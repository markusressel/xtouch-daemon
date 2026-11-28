"""
The rows of the options of a place on the page Slots ("Look in slot 2": what one candidate of a slot shows its own
way). They are the rows of the strip type, none required: unset, an option is as on the channel or in the pool the
candidate shows, and its row says so. `meter` and `meter_point` are one choice, a button is only what its LED shows
(and for Select whether it does something).
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from xtouch_daemon.gui.domain import docs
from xtouch_daemon.gui.domain.demos import GROUPS, group_of
from xtouch_daemon.gui.domain.places import Origin, inherited, inherited_part, place_help
from xtouch_daemon.gui.domain.schema import Kind, look_options
from xtouch_daemon.gui.quick.forms import meter
from xtouch_daemon.gui.quick.forms.buttons import ButtonLogic
from xtouch_daemon.gui.quick.forms.form import RowSpec

GROUP_TITLES = dict(GROUPS)
GROUP_ORDER = {group: index for index, (group, _) in enumerate(GROUPS)}


def place_specs(
    place: Origin,
    slot: int,
    strip: str,
    allowed: frozenset[str],
    pick: bool,
    get: Callable[[str], Any],
    put: Callable[[str, Any], None],
    states: Callable[[], list[str]] = list,
) -> list[RowSpec]:
    """
    The rows of a place of `strip` that takes the options `allowed`, for the candidate that shows `place`. `pick`:
    the encoder may pick. `get(name)` reads an option of the place, `put(name, value)` writes it (None removes it);
    `states` the modes and states a press can name.
    """
    specs: list[RowSpec] = []
    for option in look_options(strip, allowed):
        name = option.name
        if name == "meter_point":
            continue
        # a switch and the colors show the value they take unset as if it were set: the help says it too
        value = inherited(place, name, pick) if option.kind in (Kind.SWITCH, Kind.COLOR) else None
        help_text = place_help(place, name, slot, value)
        common: dict[str, Any] = {
            "group": GROUP_TITLES[group_of(name)],
            "link": docs.guide_link("slots"),
            "inherited": place.prefix,
            "reset_tip": place.back,
        }
        if name == "meter":
            specs.append(
                RowSpec(
                    dataclasses.replace(meter.METER, help=help_text),
                    placeholder=lambda: inherited(place, "meter", pick) or "",
                    names=("meter", "meter_point"),
                    get=lambda: meter.shown(get),
                    put=lambda value: meter.chosen(put, value),
                    **common,
                )
            )
            continue
        # no default of its own: unset, it is as where the place takes it from
        option = dataclasses.replace(option, default=None, help=help_text)
        if option.kind == Kind.CHOICE:
            option = dataclasses.replace(option, choices=tuple(c for c in option.choices if pick or c != "pick"))
        if option.kind == Kind.BUTTON:
            parts = ("press", "led") if name == "select" else ("led",)
            option = dataclasses.replace(option, columns=tuple(c for c in option.columns if c.name in parts))
        spec = RowSpec(
            option,
            placeholder=lambda name=name: inherited(place, name, pick) or "",
            get=lambda name=name: get(name),
            put=lambda value, name=name: put(name, value),
            **common,
        )
        if option.kind == Kind.BUTTON:

            def unset(part: str, name: str = name) -> str:
                value = inherited_part(place, name, part)  # pyright: ignore[reportArgumentType]
                return f"{place.prefix}: {value}" if value else place.prefix

            spec.buttons = ButtonLogic(name, option.columns, extra=states, inherited=unset)
        specs.append(spec)
    return sorted(specs, key=lambda spec: GROUP_ORDER[group_of(spec.name)])
