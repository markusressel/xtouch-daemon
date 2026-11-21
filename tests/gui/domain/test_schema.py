import dataclasses
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from xtouch_daemon.config.presets import Kind as PresetKind
from xtouch_daemon.config.sections import BehaviorConfig, DeviceConfig, MqttConfig, SwitchingConfig, VoipConfig
from xtouch_daemon.gui.domain.schema import (
    STRIP_OPTION_ORDER,
    Kind,
    Option,
    describe,
    option,
    options,
    sections,
    strip_models,
    strip_options,
    strip_type_help,
)
from xtouch_daemon.slots.model import AppsConfig, StateConfig


def strip_option(strip_type: str, name: str) -> Option:
    return next(item for item in strip_options(strip_type) if item.name == name)


def test_options_come_from_the_models_with_bounds_defaults_and_help():
    max_volume = options(BehaviorConfig)[0]
    # the help is the docstring of the field
    assert max_volume.help.startswith("The volume, in percent, with a fader at the top.")
    assert dataclasses.replace(max_volume, help="") == Option(
        name="max_volume", kind=Kind.INTEGER, help="", default=130, required=False, minimum=100, maximum=200
    )
    assert [(o.name, o.kind) for o in options(BehaviorConfig)] == [
        ("max_volume", Kind.INTEGER),
        ("unity_at", Kind.INTEGER),
        ("encoder_step", Kind.INTEGER),
        ("reset_volume", Kind.INTEGER),
        ("meters", Kind.SWITCH),
        ("meter_point", Kind.CHOICE),
    ]
    unity = options(BehaviorConfig)[1]
    assert (unity.default, unity.minimum, unity.maximum) == (77, 10, 95)
    assert "0 dB at about 77" in unity.help
    name, _virtual, touch_required, touchless, startup, shutdown = options(DeviceConfig)
    assert (touch_required.kind, touch_required.default) == (Kind.SWITCH, True)
    assert name.default == "X-Touch-Ext"
    assert (touchless.kind, touchless.default, touchless.minimum, touchless.maximum) == (Kind.NUMBERS, (), 1, 8)
    assert (startup.kind, startup.default) == (Kind.CHOICE, "sweep")
    assert shutdown.choices == ("instant", "sweep", "curtain", "show")


def test_the_options_of_a_strip_start_with_what_it_controls_and_go_down_the_device():
    names = [o.name for o in strip_options("output")]
    assert names[:3] == ["device", "choices", "profiles"]
    assert names.index("encoder") < names.index("label") < names.index("rec") < names.index("fader")
    assert names[-3:] == ["fader", "min_volume", "max_volume"]
    assert [o.name for o in strip_options("apps")][:3] == ["match", "encoder", "label"]
    assert strip_options("empty") == ()


def test_the_options_of_a_strip_take_their_kinds_bounds_and_columns_from_the_model():
    (
        device,
        choices,
        profiles,
        encoder,
        label,
        _,
        color,
        _,
        _,
        meter_point,
        rec,
        _,
        _,
        fader,
        min_volume,
        _,
    ) = strip_options("input")
    assert (meter_point.kind, meter_point.default, meter_point.choices) == (
        Kind.CHOICE,
        None,
        ("pre_fader", "post_fader"),
    )
    assert "hardware mixer" in meter_point.meaning("pre_fader")
    assert (encoder.kind, encoder.default, encoder.choices) == (
        Kind.CHOICE,
        None,
        ("balance", "volume", "homeassistant"),
    )
    assert (fader.kind, fader.default) == (Kind.CHOICE, "volume")
    assert (min_volume.kind, min_volume.default, min_volume.minimum, min_volume.maximum) == (Kind.INTEGER, None, 0, 200)
    assert (rec.kind, rec.default) == (Kind.BUTTON, None)
    assert [(column.name, column.kind) for column in rec.columns] == [
        ("press", Kind.ACTION),
        ("hold", Kind.ACTION),
        ("led", Kind.CHOICE),
    ]
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
    assert (choices.kind, choices.default) == (Kind.TABLES, ())
    assert [(column.name, column.kind, column.required) for column in choices.columns] == [
        ("label", Kind.TEXT, False),
        ("device", Kind.TEXT, True),
        ("card", Kind.TEXT, False),
        ("profile", Kind.TEXT, False),
        ("min_volume", Kind.INTEGER, False),
        ("max_volume", Kind.INTEGER, False),
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
        ("switching", SwitchingConfig, False),
        ("voip", VoipConfig, True),
    ]
    assert sections()[2].help == "The MQTT broker Home Assistant uses, for `homeassistant` strips."


def test_every_option_of_a_strip_has_its_place_in_the_order():
    # a new option goes where its part is on the device, see STRIP_OPTION_ORDER
    for strip_type, model in strip_models().items():
        for name in model.model_fields:
            assert name == "type" or name in STRIP_OPTION_ORDER, f"{strip_type}.{name} has no place"


def every_option() -> list[tuple[str, Option]]:
    """Every option the editor shows, with where it is, the columns of tables too."""
    result = [(section.name, each) for section in sections() for each in options(section.model)]
    result += [(strip_type, each) for strip_type in strip_models() for each in strip_options(strip_type)]
    return result + [(f"{where}.{each.name}", column) for where, each in result for column in each.columns]


def test_every_option_explains_itself():
    for where, each in every_option():
        assert each.help, f"{where}.{each.name} has no help"


def test_every_choice_explains_each_of_its_values():
    for where, each in every_option():
        if each.kind == Kind.CHOICE:
            for choice in each.choices:
                assert each.meaning(choice), f"{where}.{each.name}: {choice} has no meaning"
    for strip_type in strip_models():
        assert strip_type_help(strip_type)


def test_a_choice_says_what_its_value_means():
    rec = next(o for o in next(o for o in strip_options("input") if o.name == "rec").columns if o.name == "led")
    assert rec.meaning("muted") == "Lit while the strip is muted, like the Mute LED."
    assert rec.meaning("loud") == ""
    startup, shutdown = (o for o in options(DeviceConfig) if o.name in ("startup", "shutdown"))
    # the same values, but each says what it does when
    assert startup.meaning("sweep") != shutdown.meaning("sweep")
    # only the encoders of the strip type, and what they do
    encoder = next(o for o in strip_options("apps") if o.name == "encoder")
    assert encoder.choices == ("media", "volume", "balance", "homeassistant")
    assert "seeks in the track" in encoder.meaning("media")
    # the colors name themselves, but off needs a word
    color = next(o for o in strip_options("auto") if o.name == "color")
    assert (color.meaning("off"), color.meaning("red")) == ("No backlight.", "")
    assert strip_type_help("empty") == "A dark strip that does nothing; its fader stays at the bottom."


def test_the_default_for_people():
    by_name = {o.name: o for o in options(BehaviorConfig)}
    assert by_name["meters"].default_text == "on"
    assert by_name["max_volume"].default_text == "130"
    # none: the help says what happens without it
    assert next(o for o in strip_options("output") if o.name == "min_volume").default_text == ""
    assert next(o for o in strip_options("output") if o.name == "device").default_text == ""
    assert next(o for o in options(MqttConfig) if o.name == "host").default_text == ""
    assert describe(False) == "off"
    assert describe(()) == "none"
    assert describe(None) == "not set"


def test_lists_of_names_say_which_presets_they_take():
    assert strip_option("apps", "match").presets == PresetKind.STREAMS
    assert next(item for item in options(AppsConfig) if item.name == "exclude").presets == PresetKind.STREAMS
    state = {item.name: item for item in options(StateConfig)}
    assert state["apps"].presets == PresetKind.STREAMS
    assert state["processes"].presets == PresetKind.PROCESSES
    assert state["processes"].kind == Kind.LIST
    assert strip_option("output", "device").presets is None
