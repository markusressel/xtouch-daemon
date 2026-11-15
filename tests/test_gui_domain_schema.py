from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from xtouch_daemon.config import BehaviorConfig, DeviceConfig
from xtouch_daemon.gui.domain.schema import Kind, Option, option, options, strip_models, strip_options


def test_options_come_from_the_models_with_bounds_defaults_and_help():
    assert options(BehaviorConfig)[0] == Option(
        name="max_volume",
        kind=Kind.INTEGER,
        help="The volume of a fader at the top, in percent: above 100 % the audio is amplified in software.",
        default=100,
        required=False,
        minimum=100,
        maximum=150,
    )
    assert [(o.name, o.kind) for o in options(BehaviorConfig)] == [
        ("max_volume", Kind.INTEGER),
        ("encoder_step", Kind.INTEGER),
        ("reset_volume", Kind.INTEGER),
        ("meters", Kind.SWITCH),
        ("auto_hold", Kind.NUMBER),
        ("ignore", Kind.LIST),
    ]
    assert options(DeviceConfig)[0].default == "X-Touch-Ext"


def test_every_strip_type_has_its_model_and_options():
    assert list(strip_models()) == ["output", "input", "apps", "auto", "empty"]
    assert [o.name for o in strip_options("output")] == ["color", "meter", "device", "label", "select"]
    assert strip_options("empty") == ()

    color, _, device, label, _ = strip_options("input")
    assert color.kind == Kind.COLOR
    assert color.choices == ("off", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
    assert color.default == "white"
    # unset by default: the default device, the default label
    assert (device.kind, device.default, device.required) == (Kind.TEXT, None, False)
    assert (label.max_length, label.required) == (7, False)


def test_required_options_have_no_default():
    match, label = (o for o in strip_options("apps") if o.name in ("match", "label"))
    assert (match.kind, match.required, match.default) == (Kind.LIST, True, None)
    assert (label.required, label.max_length) == (True, 7)


def test_a_new_option_shows_up_without_changes():
    # like `rec` and `solo`, which are on their way: an indicator name for a button LED
    class Strip(BaseModel):
        model_config = ConfigDict(use_attribute_docstrings=True)

        rec: Literal["recording", "playing", "default", "muted", "off"] = "off"
        """What the LED of the rec button shows."""
        count: Annotated[int, Field(ge=1)] = 3

    rec, count = options(Strip)
    assert rec == Option("rec", Kind.CHOICE, "What the LED of the rec button shows.", "off", False, choices=rec.choices)
    assert rec.choices == ("recording", "playing", "default", "muted", "off")
    assert rec.title == "Rec"
    assert (count.minimum, count.maximum, count.help) == (1, None, "")


def test_an_option_without_a_form_field_is_an_error():
    class Strip(BaseModel):
        weights: dict[str, int] = {}

    with pytest.raises(TypeError, match="no form field for options of type dict"):
        option("weights", Strip.model_fields["weights"])


def test_the_title_is_readable():
    assert options(BehaviorConfig)[0].title == "Max volume"
