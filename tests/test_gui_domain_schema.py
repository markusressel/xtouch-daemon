from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from xtouch_daemon.config import BehaviorConfig, DeviceConfig, MqttConfig, SwitchingConfig, VoipConfig
from xtouch_daemon.gui.domain.schema import (
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


def test_options_come_from_the_models_with_bounds_defaults_and_help():
    assert options(BehaviorConfig)[0] == Option(
        name="max_volume",
        kind=Kind.INTEGER,
        help="The volume of a fader at the top, in percent: above 100 % the audio is amplified in software. Strips may "
        "have a\nrange of their own (`min_volume`, `max_volume`). 130 puts 100 % at the 0 dB mark of the device (see "
        "`unity_at`)\nwith the same slope above it as below, so the fader is linear over its whole travel.",
        default=130,
        required=False,
        minimum=100,
        maximum=200,
    )
    assert [(o.name, o.kind) for o in options(BehaviorConfig)] == [
        ("max_volume", Kind.INTEGER),
        ("unity_at", Kind.INTEGER),
        ("encoder_step", Kind.INTEGER),
        ("reset_volume", Kind.INTEGER),
        ("meters", Kind.SWITCH),
        ("auto_hold", Kind.NUMBER),
        ("ignore", Kind.LIST),
    ]
    unity = options(BehaviorConfig)[1]
    assert (unity.default, unity.minimum, unity.maximum) == (77, 10, 95)
    assert "0 dB at about\n77" in unity.help
    name, touch_required, touchless, startup, shutdown = options(DeviceConfig)
    assert (touch_required.kind, touch_required.default) == (Kind.SWITCH, True)
    assert name.default == "X-Touch-Ext"
    assert (touchless.kind, touchless.default, touchless.minimum, touchless.maximum) == (Kind.NUMBERS, (), 1, 8)
    assert (startup.kind, startup.default) == (Kind.CHOICE, "sweep")
    assert shutdown.choices == ("instant", "sweep", "curtain", "show")


def test_every_strip_type_has_its_model_and_options():
    assert list(strip_models()) == ["output", "input", "apps", "auto", "homeassistant", "empty", "inherit", "voip"]
    assert [o.name for o in strip_options("output")] == [
        "color",
        "lit_when_idle",
        "meter",
        "rec",
        "solo",
        "min_volume",
        "max_volume",
        "encoder",
        "fader",
        "id",
        "device",
        "label",
        "select",
        "profiles",
    ]
    assert strip_options("empty") == ()

    color, _, _, rec, _, min_volume, _, encoder, fader, _, device, label, _, profiles = strip_options("input")
    assert (encoder.kind, encoder.default, encoder.choices) == (
        Kind.CHOICE,
        None,
        ("balance", "volume", "homeassistant"),
    )
    assert (fader.kind, fader.default) == (Kind.CHOICE, "volume")
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
        ("switching", SwitchingConfig, False),
        ("voip", VoipConfig, True),
    ]
    assert sections()[2].help == "The MQTT broker Home Assistant uses, for `homeassistant` strips."


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
    rec = next(o for o in strip_options("input") if o.name == "rec")
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
    assert by_name["ignore"].default_text == "speech-dispatcher"
    assert by_name["max_volume"].default_text == "130"
    # none: the help says what happens without it
    assert next(o for o in strip_options("output") if o.name == "min_volume").default_text == ""
    assert next(o for o in strip_options("output") if o.name == "device").default_text == ""
    assert next(o for o in options(MqttConfig) if o.name == "host").default_text == ""
    assert describe(False) == "off"
    assert describe(()) == "none"
    assert describe(None) == "not set"
