"""How the state of an entity becomes what a part shows, and the value a fader or an encoder sets."""

import pytest

from xtouch_daemon.config.bindings import EntityValueBinding
from xtouch_daemon.homeassistant.domains import domain_value
from xtouch_daemon.homeassistant.parts import (
    PRESENT,
    color_of,
    led_of,
    line_of,
    nearest_color,
    number_text,
    range_of,
    text_of,
    value_of,
)
from xtouch_daemon.homeassistant.states import EntityState


def entity(entity_id: str, state: str, **attributes: object) -> EntityState:
    return EntityState(entity_id, state, attributes)


@pytest.mark.parametrize(
    ("number", "text"),
    [(21.456, "21.5"), (1013.25, "1013"), (3.14159, "3.14"), (0.05, "0.05"), (20.0, "20"), (-0.001, "0"), (5, "5")],
)
def test_numbers_are_short_for_the_lcd(number: float, text: str) -> None:
    assert number_text(number) == text


def test_the_text_of_an_entity_is_its_state_with_its_unit_or_an_attribute() -> None:
    assert text_of(entity("sensor.t", "21.456", unit_of_measurement="°C"), None) == "21.5°C"
    assert text_of(entity("sensor.h", "45", unit_of_measurement="%"), None) == "45%"
    assert text_of(entity("sensor.p", "3.25", unit_of_measurement="kW"), None) == "3.25 kW"
    assert text_of(entity("sensor.n", "7"), None) == "7"
    assert text_of(entity("media_player.tv", "playing", media_title="Song 2"), None) == "playing"
    assert text_of(entity("media_player.tv", "playing", media_title="Song 2"), "media_title") == "Song 2"
    assert text_of(entity("climate.x", "heat", temperature=21.26), "temperature") == "21.3"
    assert text_of(entity("light.x", "on", on=True), "on") == "on"
    assert text_of(entity("light.x", "on", rgb=[255, 0, 0]), "rgb") == "255, 0, 0"
    # not known: nothing
    assert text_of(entity("sensor.t", "unavailable"), None) is None
    assert text_of(entity("sensor.t", "21"), "missing") is None


@pytest.mark.parametrize(
    ("rgb", "name"),
    [
        ((0, 0, 0), "off"),
        ((255, 255, 255), "white"),
        ((255, 240, 230), "white"),
        ((255, 0, 0), "red"),
        ((10, 200, 30), "green"),
        ((0, 0, 255), "blue"),
        ((255, 180, 100), "yellow"),
        ((200, 0, 255), "magenta"),
        ((0, 255, 255), "cyan"),
    ],
)
def test_the_nearest_color_of_the_lcd(rgb: tuple[int, int, int], name: str) -> None:
    assert nearest_color(*rgb) == name


def test_the_color_of_an_entity() -> None:
    # a light: its color, off while it is off, white without a color of its own
    assert color_of(entity("light.desk", "on", rgb_color=[255, 0, 0]), None) == "red"
    assert color_of(entity("light.desk", "on", hs_color=[240, 100]), None) == "blue"
    assert color_of(entity("light.desk", "on", hs_color=[240, "x"]), None) == "white"
    assert color_of(entity("light.desk", "on", brightness=100), None) == "white"
    assert color_of(entity("light.desk", "off"), None) == "off"
    assert color_of(entity("light.desk", "unavailable"), None) is None
    # another entity: a state that is a color name
    assert color_of(entity("input_select.color", "Cyan"), None) == "cyan"
    assert color_of(entity("input_select.color", "plaid"), None) is None
    assert color_of(entity("input_select.color", "unknown"), None) is None
    # an attribute: a name, or red, green and blue
    assert color_of(entity("sensor.x", "1", tint="green"), "tint") == "green"
    assert color_of(entity("sensor.x", "1", tint=[0, 0, 255]), "tint") == "blue"
    assert color_of(entity("sensor.x", "1", tint=[0, "a", 255]), "tint") is None
    assert color_of(entity("sensor.x", "1", tint=7), "tint") is None


def test_the_led_of_an_entity() -> None:
    for state in ("on", "open", "playing", "home", "ON"):
        assert led_of(entity("x.y", state), None) == "on"
    # the words of a watch are left to it
    assert led_of(entity("x.y", "flash"), None) == "flash"
    assert led_of(entity("x.y", "off"), None) == "off"
    assert led_of(entity("x.y", "unavailable"), None) is None
    assert led_of(entity("x.y", "on", locked=True), "locked") == "on"
    assert led_of(entity("x.y", "on", locked=False), "locked") == "off"
    assert led_of(entity("x.y", "on"), "missing") is None


def test_lines_of_the_parts() -> None:
    sensor = entity("sensor.cpu", "42.5")
    assert line_of(sensor, None, "level", True) == "42.500000"
    assert line_of(entity("sensor.cpu", "high"), None, "level", True) is None
    assert line_of(entity("sensor.cpu", "unknown"), None, "level", True) is None
    assert line_of(sensor, None, "text", True) == "42.5"
    assert line_of(sensor, None, "led", True) == "42.5"
    assert line_of(entity("light.x", "off"), None, "color", True) == "off"
    assert line_of(None, None, "text", True) is None
    # present: there unless unavailable or unknown; unknown itself until the states were in once
    assert line_of(sensor, None, "present", True) == PRESENT
    assert line_of(entity("device_tracker.phone", "not_home"), None, "present", True) == PRESENT
    assert line_of(entity("sensor.cpu", "unavailable"), None, "present", True) == ""
    assert line_of(sensor, "missing", "present", True) == ""
    assert line_of(None, None, "present", True) == ""
    assert line_of(None, None, "present", False) is None


def binding(**options: object) -> EntityValueBinding:
    return EntityValueBinding.model_validate(options)


def test_the_values_of_the_domains() -> None:
    light = binding(entity="light.desk")
    assert range_of(None, light) == (0, 255)
    assert value_of(entity("light.desk", "on", brightness=128), light) == 128
    assert value_of(entity("light.desk", "off"), light) == 0
    assert value_of(entity("light.desk", "unavailable"), light) is None
    assert value_of(None, light) is None
    volume = binding(entity="media_player.tv")
    assert range_of(None, volume) == (0, 1)
    assert value_of(entity("media_player.tv", "off"), volume) is None
    assert value_of(entity("media_player.tv", "on", volume_level=0.4), volume) == 0.4
    # a number tells its range, unless the binding says it
    number = binding(entity="input_number.level")
    level = entity("input_number.level", "12", min=-10, max=30, step=1)
    assert range_of(level, number) == (-10, 30)
    assert range_of(entity("input_number.level", "12"), number) == (0, 100)
    assert range_of(level, binding(entity="input_number.level", min=0, max=20)) == (0, 20)
    assert value_of(level, number) == 12
    # another attribute with a service of its own
    custom = binding(entity="light.desk", attribute="color_temp", service="script.warmth", data={"v": "{value}"})
    assert domain_value("light.desk", "color_temp") is None
    assert range_of(None, custom) == (0, 100)
    assert value_of(entity("light.desk", "on", color_temp=300), custom) == 300
    assert value_of(entity("light.desk", "off"), custom) is None
    # a range that is none
    assert range_of(entity("number.x", "1", min=5, max=5), binding(entity="number.x")) == (5, 6)
