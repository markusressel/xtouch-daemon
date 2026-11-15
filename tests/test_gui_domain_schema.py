from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from xtouch_daemon.config import BehaviorConfig, DeviceConfig, MqttConfig
from xtouch_daemon.gui.domain.schema import Kind, Option, option, options, sections, strip_models, strip_options


def test_options_come_from_the_models_with_bounds_defaults_and_help():
    assert options(BehaviorConfig)[0] == Option(
        name="max_volume",
        kind=Kind.INTEGER,
        help="The volume of a fader at the top, in percent: above 100 % the audio is amplified in software. Strips may "
        "have a\nrange of their own (`min_volume`, `max_volume`).",
        default=100,
        required=False,
        minimum=100,
        maximum=200,
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
    assert list(strip_models()) == ["output", "input", "apps", "auto", "homeassistant", "empty"]
    assert [o.name for o in strip_options("output")] == [
        "color",
        "meter",
        "rec",
        "solo",
        "min_volume",
        "max_volume",
        "encoder",
        "device",
        "label",
        "select",
        "profiles",
    ]
    assert strip_options("empty") == ()

    color, _, rec, _, min_volume, _, encoder, device, label, _, profiles = strip_options("input")
    assert (encoder.kind, encoder.default, encoder.choices) == (Kind.CHOICE, None, ("balance", "volume"))
    assert (min_volume.kind, min_volume.default, min_volume.minimum, min_volume.maximum) == (Kind.INTEGER, None, 0, 200)
    assert (rec.kind, rec.default) == (Kind.CHOICE, "recording")
    assert color.kind == Kind.COLOR
    assert color.choices == ("off", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
    assert color.default == "white"
    # unset by default: the default device, the default label
    assert (device.kind, device.default, device.required) == (Kind.LIST, (), False)
    assert (label.max_length, label.required) == (7, False)
    # a list of tables, with options of their own
    assert (profiles.kind, profiles.default) == (Kind.TABLES, ())
    assert [(column.name, column.kind, column.max_length) for column in profiles.columns] == [
        ("label", Kind.TEXT, 7),
        ("profile", Kind.TEXT, None),
        ("min_volume", Kind.INTEGER, None),
        ("max_volume", Kind.INTEGER, None),
    ]


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


def test_secrets_and_paths_have_kinds_of_their_own():
    kinds = {o.name: o.kind for o in options(MqttConfig)}
    assert kinds["password"] == Kind.SECRET
    assert kinds["password_file"] == Kind.PATH
    assert kinds["password_env"] == Kind.TEXT
    assert next(o for o in options(MqttConfig) if o.name == "host").required


def test_the_sections_with_options_of_their_own():
    assert [(s.name, s.model, s.optional) for s in sections()] == [
        ("device", DeviceConfig, False),
        ("behavior", BehaviorConfig, False),
        ("mqtt", MqttConfig, True),
    ]
    assert sections()[2].help == "The MQTT broker Home Assistant uses, for `homeassistant` strips."
