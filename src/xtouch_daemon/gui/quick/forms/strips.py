"""
The form of a channel (or a pool) from its type: the rows of the options of its strip in the order of the device, in
groups, with what each suggests and takes unset, `device` and `choices` as one list, `meter` and `meter_point` as one
choice, and the buttons with what the strip type does by default.

For the page of the channels, a few lines:

    form = channel_form(forms_of(app), "output")        # once per type of channel; the page keeps it
    form.retarget(("channel", "speakers"))              # for the channel picked
    # in QML: FormView { form: ... }

`pool_form` is the same for the built-in pools and the pools of your own.
"""

from collections.abc import Callable
from typing import Any

from xtouch_daemon.audio.model import Direction
from xtouch_daemon.config.buttons import ButtonSetup, default_setup
from xtouch_daemon.config.values import ENCODERS, default_encoder
from xtouch_daemon.gui.domain import docs, sources
from xtouch_daemon.gui.domain.channels import BUILT_IN_POOLS, channel_options, lcd_default, pool_options
from xtouch_daemon.gui.domain.demos import GROUPS, PREVIEWED, group_of
from xtouch_daemon.gui.domain.schema import Kind, Option, options
from xtouch_daemon.gui.domain.slot_controls import modes_and_states
from xtouch_daemon.gui.domain.sources import Suggestion
from xtouch_daemon.gui.domain.voip import participants
from xtouch_daemon.gui.quick.forms import meter, tables
from xtouch_daemon.gui.quick.forms.buttons import ButtonLogic
from xtouch_daemon.gui.quick.forms.context import FormContext
from xtouch_daemon.gui.quick.forms.form import Form, RowSpec
from xtouch_daemon.gui.quick.forms.suggestions import Suggest, TableSuggest
from xtouch_daemon.live.messages import ForgetDevice, KnownDevice
from xtouch_daemon.slots.model import AppsPoolConfig, PeoplePoolConfig, PoolConfig

type Where = Callable[[], tuple[str, ...]]
"""Where the channel or pool of the form is in the document, e.g. `("channel", "speakers")`."""

GROUP_TITLES = dict(GROUPS)
GROUP_ORDER = {group: index for index, (group, _) in enumerate(GROUPS)}


def _forget(context: FormContext, device: KnownDevice) -> None:
    context.send(ForgetDevice(device.name, device.direction))


def _suggestions(context: FormContext, strip: str) -> tuple[dict[str, Suggest], dict[str, TableSuggest]]:
    """What the options of a strip type suggest (the sound server, the voice chat, the channels of the file)."""
    document = context.editor.document

    def channels() -> tuple[Suggestion, ...]:
        """What a pool of channels can list: the channels by id, and the tags (`#tag`) of the channels."""
        found = document.get(("channel",), {})
        names = [Suggestion(name, str(channel.get("type"))) for name, channel in found.items()]
        tags = sorted({tag for channel in found.values() for tag in channel.get("tags", ())})
        return (*names, *(Suggestion(f"#{tag}", "every channel with this tag") for tag in tags))

    suggest: dict[str, Suggest] = {
        "match": lambda: sources.patterns(context.audio()),
        "exclude": lambda: sources.patterns(context.audio()),
        "person": lambda: participants(context.snapshot()),
        "channels": channels,
    }
    table_suggest: dict[str, TableSuggest] = {}
    if strip in ("output", "input"):
        direction = Direction(strip)

        def devices(_line: dict[str, Any]) -> tuple[Suggestion, ...]:
            """The devices there are, those of other profiles and those the daemon remembers."""
            return sources.devices(
                context.audio(), direction, context.known(), context.clock(), lambda device: _forget(context, device)
            )

        suggest["profiles"] = lambda: sources.profiles(context.audio(), direction)
        table_suggest["choices"] = {
            "device": devices,
            "card": lambda _line: sources.cards(context.audio()),
            "profile": lambda line: sources.card_profiles(context.audio(), str(line.get("card", ""))),
        }
    return suggest, table_suggest


def strip_rows(context: FormContext, strip: str, form_options: tuple[Option, ...], where: Where) -> list[RowSpec]:
    """
    The rows of the options of a strip type, grouped as the device is, with `where()` the place of the channel or
    pool in the document (it can change: the form is for every channel of the type).
    """
    document = context.editor.document
    suggest, table_suggest, placeholders = (*_suggestions(context, strip), _placeholders(context, strip, where))
    by_name = {option.name: option for option in form_options}

    def read(name: str) -> Any:
        return document.get((*where(), name))

    def write(name: str, value: Any) -> None:
        if value is None:
            document.unset((*where(), name))
        else:
            document.set((*where(), name), value)

    specs: list[RowSpec] = []
    for option in form_options:
        name = option.name
        group = group_of(name)
        extra: dict[str, Any] = {
            "group": GROUP_TITLES[group],
            "preview": group if group in PREVIEWED else "",
        }
        if name == "meter_point" and "meter" in by_name:
            continue
        if name == "choices" and "device" in by_name:
            continue
        if name == "meter" and "meter_point" in by_name:
            bound = option.kind == Kind.BINDING
            specs.append(
                RowSpec(
                    meter.BOUND_METER if bound else meter.METER,
                    placeholder=lambda: str(document.get(("behavior", "meter_point"), "pre_fader")),
                    link=docs.option_link("strip", "meter_point", strip),
                    names=("meter", "meter_point"),
                    get=lambda: meter.shown(read),
                    put=lambda value: meter.chosen(write, value),
                    **extra,
                )
            )
            continue
        if name == "device" and "choices" in by_name:
            specs.append(
                RowSpec(
                    tables.device_option(option, by_name["choices"]),
                    suggest=table_suggest.get("choices"),
                    link=docs.option_link("strip", "device", strip),
                    names=("device", "choices"),
                    get=lambda: tables.entries_of(read("device"), read("choices")) or None,
                    put=lambda entries: _write_devices(write, entries),
                    **extra,
                )
            )
            continue
        spec = RowSpec(
            option,
            suggest=table_suggest.get(name) or suggest.get(name),
            placeholder=placeholders.get(name),
            link=docs.option_link("strip", name, strip, bound=option.kind == Kind.BINDING),
            **extra,
        )
        if option.kind == Kind.BUTTON:
            spec.buttons = _button(context, strip, option, where)
        specs.append(spec)
    return sorted(specs, key=lambda spec: GROUP_ORDER[group_of(spec.name)] if spec.group else 0)


def _write_devices(write: Callable[[str, Any], None], entries: list[tables.Entry] | None) -> None:
    names, found = tables.written(entries or [])
    write("device", names)
    write("choices", found)


def _placeholders(context: FormContext, strip: str, where: Where) -> dict[str, Callable[[], str]]:
    document = context.editor.document

    def encoder() -> str:
        if strip in ENCODERS:
            return default_encoder(strip, document.get((*where(), "fader")) or "volume")
        return "the value of the fader, by its step"

    placeholders: dict[str, Callable[[], str]] = {
        "encoder": encoder,
        "lcd": lambda: lcd_default(strip),
        "min_volume": lambda: "0",
        "max_volume": lambda: f"{document.get(('behavior', 'max_volume'), 130)} (behavior)",
        # one entry per part: the program first, then each argument
        "launch": lambda: "none: Select starts nothing; the program, then each argument",
    }
    if strip == "custom":
        placeholders["fader"] = lambda: "none: the fader stays down"
        placeholders["meter"] = lambda: "none: the meter stays dark"
        placeholders["present"] = lambda: "none: always present"
    return placeholders


def _button(context: FormContext, strip: str, option: Option, where: Where) -> ButtonLogic:
    """A button shows what the strip type does without its table, and offers the modes and states there are."""
    document = context.editor.document

    def defaults() -> ButtonSetup:
        if strip == "custom":
            # a button of a custom channel does nothing unless it is told to
            return ButtonSetup()
        place = where()
        return default_setup(
            option.name,  # pyright: ignore[reportArgumentType]: a button option is named like its button
            strip,
            devices=bool(document.get((*place, "device")) or document.get((*place, "choices"))),
            profiles=bool(document.get((*place, "profiles"))),
            launch=document.get((*place, "launch")) is not None,
        )

    return ButtonLogic(option.name, option.columns, defaults=defaults, extra=lambda: modes_and_states(document.values))


def channel_form(context: FormContext, channel_type: str, where: tuple[str, ...] = ()) -> Form:
    """The form of the channels of a type: `form.retarget(("channel", id))` points it at a channel."""
    form = Form(context, base=where)
    form.set_specs(strip_rows(context, channel_type, channel_options(channel_type), lambda: form.base))
    return form


def pool_form(context: FormContext, pool: str, kind: str | None = None, where: tuple[str, ...] = ()) -> Form:
    """
    The form of a pool: a built-in one (`apps`, `people`, `devices`, `auto`) by its name, one of your own by its
    kind (`None` for a pool of channels, `"apps"` or `"people"`).
    """
    if pool in {name for name, *_ in BUILT_IN_POOLS}:
        form_options = pool_options(pool)
        strip = "voip" if pool == "people" else "auto"
    else:
        model = {"apps": AppsPoolConfig, "people": PeoplePoolConfig}.get(kind or "", PoolConfig)
        form_options = options(model)
        strip = "voip" if kind == "people" else "auto"
    form = Form(context, base=where)
    form.set_specs(strip_rows(context, strip, form_options, lambda: form.base))
    return form
