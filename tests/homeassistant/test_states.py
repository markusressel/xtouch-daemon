"""The states of the entities as `subscribe_entities` sends them: compressed, all first, then the changes."""

from xtouch_daemon.homeassistant.states import EntityState, apply_event, from_state


def test_all_entities_come_first_then_their_changes_and_removals() -> None:
    states: dict[str, EntityState] = {}
    added = {
        "light.desk": {"s": "on", "a": {"brightness": 128, "friendly_name": "Desk"}, "c": "x", "lc": 1.0},
        "sensor.cpu": {"s": "12.5", "a": {}, "c": "y", "lc": 1.0},
    }
    assert apply_event(states, {"a": added}) == {"light.desk", "sensor.cpu"}
    assert states["light.desk"] == EntityState("light.desk", "on", {"brightness": 128, "friendly_name": "Desk"})
    assert states["light.desk"].name == "Desk"
    assert states["sensor.cpu"].name == "sensor.cpu"
    # what is new comes with "+", the attributes that went with "-"
    changed = apply_event(states, {"c": {"light.desk": {"+": {"s": "off", "a": {"x": 1}}, "-": {"a": ["brightness"]}}}})
    assert changed == {"light.desk"}
    assert states["light.desk"] == EntityState("light.desk", "off", {"friendly_name": "Desk", "x": 1})
    # an attribute alone, the state stays
    apply_event(states, {"c": {"light.desk": {"+": {"a": {"x": 2}}}}})
    assert states["light.desk"].state == "off"
    assert states["light.desk"].attributes["x"] == 2
    # a change of an entity that never came is no entity
    assert apply_event(states, {"c": {"light.other": {"+": {"s": "on"}}}}) == set()
    assert "light.other" not in states
    assert apply_event(states, {"r": ["sensor.cpu", "sensor.never"]}) == {"sensor.cpu"}
    assert set(states) == {"light.desk"}


def test_unavailable_and_unknown_are_no_states() -> None:
    assert not EntityState("sensor.x", "unavailable").known
    assert not EntityState("sensor.x", "unknown").known
    assert EntityState("sensor.x", "off").known


def test_an_uncompressed_state() -> None:
    entity = from_state({"entity_id": "sensor.x", "state": "3", "attributes": {"unit_of_measurement": "W"}})
    assert entity == EntityState("sensor.x", "3", {"unit_of_measurement": "W"})
    assert from_state({"entity_id": "sensor.y"}) == EntityState("sensor.y", "", {})
