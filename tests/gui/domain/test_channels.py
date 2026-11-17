from xtouch_daemon.gui.domain.channels import (
    CHANNEL_TYPES,
    channel_options,
    free_id,
    people_options,
    pool_options,
    shown_by,
    stack_of,
    uses,
)


def test_the_options_of_a_channel_are_those_of_its_strip_and_of_slots():
    names = [option.name for option in channel_options("apps")]
    assert names[:2] == ["match", "encoder"]
    assert names[-3:] == ["absent_after", "in_auto", "tags"]
    assert "collapse" not in names
    person = [option.name for option in channel_options("person")]
    assert person[0] == "person"
    assert "launch" not in person
    assert list(CHANNEL_TYPES) == ["output", "input", "apps", "person", "homeassistant"]
    assert [option.name for option in pool_options()][:2] == ["exclude", "hold"]
    people = [option.name for option in people_options()]
    assert people[0] == "order"
    assert "person" not in people


def test_where_a_channel_is_used():
    values = {
        "slots": {"1": "out", "2": ["voip if call", {"show": "voip"}, {"show": 3}, 4], "3": 5},
        "pool": {"chat": {"channels": ["voip"]}, "odd": "x"},
        "state": {"call": {"channels": ["voip"]}},
    }
    assert uses(values, "voip") == ("slot 2", "pool chat", "state call")
    assert uses(values, "out") == ("slot 1",)
    assert uses({}, "out") == ()
    assert [shown_by(entry) for entry in stack_of(values["slots"]["2"])] == ["voip", "voip", None, None]
    assert stack_of(5) == []


def test_a_free_id():
    assert free_id({"out": 1}, "mic") == "mic"
    assert free_id({"mic": 1, "mic_2": 1}, "mic") == "mic_3"
    # auto is a pool of its own
    assert free_id(set(), "auto") == "auto_2"
