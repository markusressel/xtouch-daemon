from xtouch_daemon.gui.domain.channels import (
    CHANNEL_TYPES,
    LCD_DEFAULTS,
    channel_options,
    free_id,
    lcd_default,
    pool_options,
    shown_by,
    stack_of,
    uses,
)


def test_the_options_of_a_channel_are_those_of_its_strip_and_of_slots():
    names = [option.name for option in channel_options("apps")]
    assert names[:2] == ["match", "encoder"]
    assert names[-3:] == ["absent_after", "in_pool", "tags"]
    person = [option.name for option in channel_options("person")]
    assert person[0] == "person"
    assert "launch" not in person
    assert "label" in person
    assert list(CHANNEL_TYPES) == ["output", "input", "apps", "person", "homeassistant", "custom"]
    assert [option.name for option in pool_options("apps")][:3] == ["from", "exclude", "hold"]
    people = [option.name for option in pool_options("people")]
    assert people[:2] == ["from", "order"]
    assert "person" not in people
    assert "label" not in people
    # auto has only the look of its strips: what it takes are the options of apps and people
    assert "exclude" not in [option.name for option in pool_options("auto")]


def test_where_a_channel_is_used():
    values = {
        "slots": {"1": "out", "2": ["voip if call", {"show": "voip"}, {"show": 3}, 4], "3": 5},
        "pool": {"chat": {"channels": ["voip"]}, "odd": "x"},
        "state": {"call": {"channels": ["voip"]}},
    }
    assert uses(values, "voip") == ("slot 2", "pool chat", "state call")
    assert uses(values, "out") == ("slot 1",)
    assert uses({}, "out") == ()
    # the applications and the people share the slots of auto
    assert uses({"slots": {"3": "auto", "4": "apps"}}, "apps") == ("slot 3", "slot 4")
    assert uses({"slots": {"3": "auto"}}, "people") == ("slot 3",)
    assert uses({"slots": {"3": "auto"}}, "devices") == ()
    assert [shown_by(entry) for entry in stack_of(values["slots"]["2"])] == ["voip", "voip", None, None]
    assert stack_of(5) == []


def test_a_free_id():
    assert free_id({"out": 1}, "mic") == "mic"
    assert free_id({"mic": 1, "mic_2": 1}, "mic") == "mic_3"
    # auto is a pool of its own
    assert free_id(set(), "auto") == "auto_2"


def test_the_lcd_says_what_it_shows_unbound_by_the_type_of_the_channel() -> None:
    assert lcd_default("output") == "the volume, e.g. 46%, or muted; off while the output is not there"
    assert lcd_default("apps") == "the volume, e.g. 60%, or muted; idle while none of its applications plays"
    assert lcd_default("custom") == "the value of the fader, else of the encoder"
    # every type with an LCD to bind has its own
    with_lcd = {kind for kind in CHANNEL_TYPES if any(option.name == "lcd" for option in channel_options(kind))}
    assert with_lcd == set(LCD_DEFAULTS)
