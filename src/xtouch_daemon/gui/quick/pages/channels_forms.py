"""
The forms of the page Channels: one per type of channel (6), per built-in pool (4) and per kind of pool of your own
(3), made the first time they are asked for and kept. A form is for every channel of its type: the page points it at
the channel picked (`retarget`), so what the form shows changes in place. The previews of the parts of the strip
(encoder, display, buttons, fader) beside the options show what the options of the channel do.
"""

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import QObject, pyqtSlot  # pyright: ignore[reportUnknownVariableType]

from xtouch_daemon.config.sections import BehaviorConfig
from xtouch_daemon.gui.domain.channels import BUILT_IN_POOLS, CHANNEL_TYPES, channel_options, pool_options
from xtouch_daemon.gui.domain.demos import PREVIEWED, Part, Strip, scene
from xtouch_daemon.gui.domain.schema import Option, options
from xtouch_daemon.gui.domain.slots_document import OptionPath
from xtouch_daemon.gui.quick.device.part import PartPreviewModel
from xtouch_daemon.gui.quick.forms.context import FormContext
from xtouch_daemon.gui.quick.forms.form import Form, RowSpec
from xtouch_daemon.gui.quick.forms.strips import strip_rows
from xtouch_daemon.gui.quick.pages.channels_list import (
    CUSTOM_APPS_POOL,
    CUSTOM_PEOPLE_POOL,
    CUSTOM_POOL,
    POOLS,
    pool_kind_key,
)
from xtouch_daemon.slots.model import AppsPoolConfig, PeoplePoolConfig, PoolConfig

FORM_KEYS = (
    *CHANNEL_TYPES,
    *(f"pool.{name}" for name, *_ in BUILT_IN_POOLS),
    CUSTOM_POOL,
    CUSTOM_APPS_POOL,
    CUSTOM_PEOPLE_POOL,
)
"""The keys of the forms: a type of channel, `pool.<built-in pool>`, or `pool.custom` (with `.apps`, `.people`)."""


def form_key(selection: OptionPath, values: Mapping[str, Any]) -> str:
    """The key of the form of a channel or pool picked: of its type, of the built-in pool, or of its kind."""
    if selection in POOLS:
        return f"pool.{selection[1]}"
    section, name = selection[:2]
    entry = values.get(str(section), {}).get(str(name), {})
    if section == "pool":
        return pool_kind_key(entry.get("kind"))
    return str(entry.get("type", "apps"))


def _what_of(key: str) -> tuple[tuple[Option, ...], str]:
    """The options of the form of `key` and the type of strip they are about."""
    if key in CHANNEL_TYPES:
        return channel_options(key), key
    if key in (CUSTOM_POOL, CUSTOM_APPS_POOL, CUSTOM_PEOPLE_POOL):
        model = {CUSTOM_APPS_POOL: AppsPoolConfig, CUSTOM_PEOPLE_POOL: PeoplePoolConfig}.get(key, PoolConfig)
        return options(model), "voip" if key == CUSTOM_PEOPLE_POOL else "auto"
    pool = key.removeprefix("pool.")
    return pool_options(pool), "voip" if pool == "people" else "auto"


class ChannelForm(Form):
    """A form of the page Channels: `profiles`, the older way to switch devices, shows only where the file has it."""

    def _state(self, spec: RowSpec, values: Mapping[str, Any], problems: list[Any]) -> dict[str, Any]:
        state = super()._state(spec, values, problems)
        if spec.name == "profiles":
            state["visible"] = bool(self.editor.document.get((*self.base, "profiles")))
        return state


class ChannelForms(QObject):
    """The forms of the page and the previews of their parts."""

    def __init__(self, context: FormContext, parent: QObject) -> None:
        super().__init__(parent)  # pyright: ignore[reportArgumentType]  (PyQt6 types the parent as Self)
        self.context = context
        self.forms: dict[str, ChannelForm] = {}
        self.previews: dict[Part, PartPreviewModel] = {}
        self.options: dict[str, tuple[Option, ...]] = {}

    def form(self, key: str) -> ChannelForm:
        """The form of `key`, made the first time."""
        found = self.forms.get(key)
        if found is None:
            form_options, strip = _what_of(key)
            found = ChannelForm(self.context, base=(), parent=self)
            found.strip = strip
            found.set_specs(strip_rows(self.context, strip, form_options, lambda form=found: form.base))
            self.forms[key] = found
            self.options[key] = form_options
        return found

    def resolved(self, key: str) -> dict[str, Any]:
        """The value of each option of the form at its base, an unset one as its default (what the previews play)."""
        form = self.form(key)
        document = self.context.editor.document
        return {
            option.name: option.default if (value := document.get((*form.base, option.name))) is None else value
            for option in self.options[key]
        }

    @pyqtSlot(str, result=QObject)  # pyright: ignore[reportArgumentType]
    def partModel(self, part: str) -> PartPreviewModel:
        """The preview of a part of the strip (`encoder`, `display`, `buttons`, `fader`), made the first time."""
        assert part in PREVIEWED
        found = self.previews.get(part)  # pyright: ignore[reportArgumentType]
        if found is None:
            found = self.previews[part] = PartPreviewModel(part, self)  # pyright: ignore[reportArgumentType]
        return found

    def play(self, key: str) -> None:
        """The previews show what the channel picked does (after every edit): only the parts asked for are made."""
        if not self.previews:
            return
        config = self.context.editor.validation.config
        strip = Strip(self.form(key).strip, self.resolved(key), config.behavior if config else BehaviorConfig())
        for part, model in self.previews.items():
            model.play(scene(part, strip))
