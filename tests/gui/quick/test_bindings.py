"""Bindings: a part bound to Home Assistant, an entity, a program of your own or a custom channel."""

from typing import Any

import pytest

from tests.gui.quick.test_forms import out, rows  # noqa: F401  (the fixture)
from xtouch_daemon.gui.domain.places import HOME_ASSISTANT
from xtouch_daemon.gui.quick.forms import binding, meter
from xtouch_daemon.gui.quick.forms.form import Form


def spec(form: Form, name: str) -> dict[str, Any]:
    return rows(form)[name]["spec"]


def test_a_value_says_how_it_is_bound():
    assert binding.mode_of(None) == binding.WORDS
    assert binding.mode_of(False) == binding.WORDS
    assert binding.mode_of(HOME_ASSISTANT) == binding.HOME_ASSISTANT
    assert binding.mode_of({"entity": "light.desk"}) == binding.ENTITY
    assert binding.mode_of({"channel": "x"}) == binding.CHANNEL
    assert binding.mode_of({"launch": ["a"]}) == binding.PROGRAM


def test_binding_to_a_mode_keeps_what_the_mode_had(out: Form):  # noqa: F811
    assert out.bindValue("color", binding.CHANNEL, {}) == {"channel": ""}
    assert out.bindValue("color", binding.WORDS, {}) is None
    assert out.bindValue("color", binding.HOME_ASSISTANT, {}) == HOME_ASSISTANT
    assert out.bindValue("color", binding.PROGRAM, {binding.PROGRAM: {"watch": ["a"]}}) == {"watch": ["a"]}
    assert out.bindValue("color", binding.ENTITY, {}) == {"entity": ""}
    assert out.bindValue("color", binding.ENTITY, {binding.ENTITY: {"entity": "light.a"}}) == {"entity": "light.a"}


def test_the_menu_offers_the_modes_in_order(out: Form):  # noqa: F811
    option = out._specs["color"].option  # pyright: ignore[reportPrivateUsage]
    assert [mode["mode"] for mode in binding.modes_of(option)] == [
        binding.HOME_ASSISTANT,
        binding.ENTITY,
        binding.PROGRAM,
        binding.WORDS,
    ]


def test_the_button_says_what_it_binds_to(out: Form):  # noqa: F811
    option = out._specs["color"].option  # pyright: ignore[reportPrivateUsage]
    assert binding.bind_tip(option, None) == ("Bind it to Home Assistant, one of its entities or a program of your own")
    assert binding.bind_tip(option, HOME_ASSISTANT) == "Bound to Home Assistant: click to change"
    assert binding.bind_tip(option, {"entity": "light.a"}) == "Bound to an entity: click to change"
    assert rows(out)["color"]["info"]["bindTip"] == binding.bind_tip(option, None)


def test_a_number_of_a_program_starts_at_its_range():
    assert binding.number_start("min", {"min": 5, "max": 50}) == 5
    assert binding.number_start("step", {"min": 0, "max": 100}) == pytest.approx(
        100 * binding.DEFAULT_ENCODER_STEP / 100
    )
    # a range that is no range falls back to 0 to 100
    assert binding.number_start("min", {"min": 9, "max": 3}) == 0
    assert binding.number_start("min", {"min": "x"}) == 0


def test_problems_inside_a_binding_go_to_its_option():
    by_column, rest = binding.nested(
        [(("fader", "max"), "too high"), ((), "service: nothing sets it"), ((), "other")], {"fader", "service"}
    )
    assert by_column["fader"] == ["too high"]
    assert by_column["service"] == ["Nothing sets it"]
    assert rest == ["other"]


def test_the_meter_row_joins_the_meter_and_its_point():
    values: dict[str, Any] = {}
    assert meter.shown(values.get) is None
    values["meter"] = False
    assert meter.shown(values.get) == meter.METER_OFF
    values.update(meter=None, meter_point="output")
    assert meter.shown(values.get) == "output"
    values["meter"] = HOME_ASSISTANT
    assert meter.shown(values.get) == HOME_ASSISTANT

    written: dict[str, Any] = {}
    meter.chosen(written.__setitem__, meter.METER_OFF)
    assert written == {"meter": False, "meter_point": None}
    meter.chosen(written.__setitem__, "input")
    assert written == {"meter": None, "meter_point": "input"}
    meter.chosen(written.__setitem__, {"watch": ["x"]})
    assert written == {"meter": {"watch": ["x"]}, "meter_point": None}
