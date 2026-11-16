import re
import tomllib
from pathlib import Path

import pytest

from xtouch_daemon.config import ConfigError, Problem, example_config, parse_config
from xtouch_daemon.gui.domain.document import ConfigDocument, StripDraft

FILE = """\
# my mixer
[behavior]
max_volume = 120   # loud
meters = false

[aliases]
# what auto strips show
"WEBRTC VoiceEngine" = "Discord"

# devices first

[[strip]]
type = "output"   # the speakers
device = "alsa_output.analog"
label = "Speaker"
color = "cyan"

[[strip]]
type = "apps"
match = ["brave"]
label = "Browser"
# the end of the browsers

[[strip]]
type = "empty"
"""


def document(text: str = FILE, path: Path = Path("/nonexistent/config.toml")) -> ConfigDocument:
    return ConfigDocument(path, text, exists=True)


def test_unchanged_it_writes_the_file_as_it_was():
    assert document().render() == FILE
    assert ConfigDocument(Path("/x"), example_config(), exists=False).render() == example_config()


def test_reads_the_options_as_data():
    doc = document()

    assert doc.sections == {
        "device": {},
        "behavior": {"max_volume": 120, "meters": False},
        "mqtt": None,
        "switching": {},
        "voip": None,
    }
    assert doc.aliases == [("WEBRTC VoiceEngine", "Discord")]
    assert [strip.type for strip in doc.strips] == ["output", "apps", "empty"]
    assert doc.get(("strip", 1, "match")) == ["brave"]
    assert doc.get(("behavior", "encoder_step")) is None
    assert not doc.modified
    assert doc.data() == tomllib.loads(FILE)


def test_a_changed_option_keeps_the_comments():
    doc = document()
    doc.set(("behavior", "max_volume"), 130)
    doc.set(("strip", 0, "label"), "Boxes")

    text = doc.render()

    assert "max_volume = 130   # loud\n" in text
    assert 'label = "Boxes"\n' in text
    assert 'type = "output"   # the speakers\n' in text
    assert doc.modified
    assert tomllib.loads(text) == doc.data()


def test_a_removed_option_goes_back_to_its_default():
    doc = document()
    doc.unset(("behavior", "meters"))
    doc.unset(("strip", 0, "device"))

    text = doc.render()

    assert "meters" not in text
    assert "device =" not in text
    assert parse_config(text).behavior.meters is True


def test_a_new_option_goes_after_the_last_option_of_its_table():
    doc = document()
    doc.set(("behavior", "encoder_step"), 2)
    doc.aliases.append(("Firefox", "Fox"))
    doc.set(("strip", 1, "color"), "yellow")

    text = doc.render()

    assert "meters = false\nencoder_step = 2\n\n[aliases]" in text
    assert '"WEBRTC VoiceEngine" = "Discord"\nFirefox = "Fox"\n\n# devices first' in text
    assert 'label = "Browser"\ncolor = "yellow"\n# the end of the browsers\n' in text


def test_a_new_section_goes_before_the_ones_after_it():
    doc = document('# just strips\n\n[[strip]]\ntype = "auto"\n')
    doc.set(("device", "name"), "X-Touch-Ext 2")
    doc.aliases.append(("a", "b"))

    assert doc.render() == (
        '# just strips\n\n[device]\nname = "X-Touch-Ext 2"\n\n[aliases]\na = "b"\n\n[[strip]]\ntype = "auto"\n'
    )


def test_a_new_section_in_an_empty_file():
    doc = document("")
    doc.set(("behavior", "encoder_step"), 3)
    doc.add_strip("auto")

    assert tomllib.loads(doc.render()) == {"behavior": {"encoder_step": 3}, "strip": [{"type": "auto"}]}


def test_a_moved_strip_takes_its_comments_along():
    doc = document()
    doc.move_strip(0, 2)

    text = doc.render()

    assert [strip["type"] for strip in tomllib.loads(text)["strip"]] == ["apps", "empty", "output"]
    assert text.endswith(
        '[[strip]]\ntype = "apps"\nmatch = ["brave"]\nlabel = "Browser"\n# the end of the browsers\n\n'
        '[[strip]]\ntype = "empty"\n\n'
        '[[strip]]\ntype = "output"   # the speakers\ndevice = "alsa_output.analog"\n'
        'label = "Speaker"\ncolor = "cyan"\n'
    )


def test_strips_can_be_added_and_removed():
    doc = document()
    doc.remove_strip(1)
    assert doc.add_strip("input") == 2
    doc.set(("strip", 2, "label"), "Mic")

    data = tomllib.loads(doc.render())

    assert data["strip"] == [
        {"type": "output", "device": "alsa_output.analog", "label": "Speaker", "color": "cyan"},
        {"type": "empty"},
        {"type": "input", "label": "Mic"},
    ]


def test_without_strips_there_is_no_strip_left():
    doc = document()
    for _ in range(3):
        doc.remove_strip(0)

    assert "[[strip]]" not in doc.render()
    # and none comes from nowhere
    assert "[[strip]]" not in document("").render()


def test_at_most_eight_strips():
    doc = document("")
    doc.configure_up_to(7)
    assert [strip.type for strip in doc.strips] == ["auto"] * 8
    doc.configure_up_to(3)
    assert len(doc.strips) == 8

    with pytest.raises(ValueError, match="there are 8 strips already"):
        doc.add_strip()


def test_a_new_type_keeps_the_options_it_has_too():
    doc = document()
    doc.set_strip_type(0, "apps")
    assert doc.strips[0].values == {"type": "apps", "label": "Speaker", "color": "cyan"}

    doc.set_strip_type(0, "empty")
    assert doc.strips[0].values == {"type": "empty"}


def test_validation_uses_the_models():
    doc = document()
    assert doc.validate().config == parse_config(FILE)
    assert doc.validate().problems == []

    doc.unset(("strip", 1, "label"))
    doc.set(("behavior", "reset_volume"), 140)
    validation = doc.validate()

    assert validation.config is None
    assert validation.problems == [
        Problem(("behavior",), "reset_volume (140) is above max_volume (120)", "value_error"),
        Problem(("strip", 1, "label"), "Field required", "missing"),
    ]
    assert validation.at("strip", 1) == [validation.problems[1]]
    assert validation.at("strip", 0) == []


def test_aliases_need_a_name_and_one_alias_per_name():
    doc = document()
    doc.aliases += [("", "x"), ("WEBRTC VoiceEngine", "Voice")]

    assert doc.validate().problems == [
        Problem(("aliases", "WEBRTC VoiceEngine"), "there are several aliases for it", "duplicate"),
        Problem(("aliases", ""), "the name of the application is missing", "missing"),
    ]


def test_unknown_options_and_sections_can_be_removed():
    doc = document('typo = 1\n[behavior]\nmax_volum = 120\n[[strip]]\ntype = "auto"\ncolour = "red"\n')
    assert {problem.kind for problem in doc.validate().problems} == {"extra_forbidden"}

    for problem in doc.validate().problems:
        doc.unset(problem.path)

    assert doc.validate().problems == []
    assert doc.render() == '[behavior]\n[[strip]]\ntype = "auto"\n'


def test_an_option_that_is_not_there_is_an_error():
    with pytest.raises(KeyError, match="no option at"):
        document().get(("nothing",))


def test_saving_writes_the_file_and_reads_it_again(tmp_path: Path):
    path = tmp_path / "new" / "config.toml"
    doc = ConfigDocument.open(path)
    assert not doc.exists
    doc.set(("behavior", "encoder_step"), 2)

    config = doc.save()

    assert config.behavior.encoder_step == 2
    assert doc.exists
    assert not doc.modified
    assert path.read_text() == doc.render()
    assert ConfigDocument.open(path).data() == doc.data()
    # the strips are where they are in the file now
    assert [strip.origin for strip in doc.strips] == list(range(8))


def test_saving_keeps_a_symlink(tmp_path: Path):
    target = tmp_path / "dotfiles.toml"
    target.write_text(FILE)
    link = tmp_path / "config.toml"
    link.symlink_to(target)
    doc = ConfigDocument.open(link)
    doc.set(("behavior", "max_volume"), 110)

    doc.save()

    assert link.is_symlink()
    assert "max_volume = 110" in target.read_text()


def test_a_configuration_with_problems_is_not_saved(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(FILE)
    doc = ConfigDocument.open(path)
    doc.set(("behavior", "max_volume"), 300)

    with pytest.raises(ConfigError, match=r"has errors:\n  behavior.max_volume: Input should be less than"):
        doc.save()
    assert path.read_text() == FILE


def test_revert_drops_the_changes(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(FILE)
    doc = ConfigDocument.open(path)
    doc.remove_strip(0)
    doc.revert()
    assert doc.data() == tomllib.loads(FILE)

    new = ConfigDocument.open(tmp_path / "missing.toml")
    new.remove_strip(0)
    new.revert()
    assert new.data() == tomllib.loads(example_config())


def test_sections_that_take_a_restart_are_noticed():
    doc = document()
    assert doc.restart_sections == ()
    # the faders without a touch sensor change with a reload
    doc.set(("device", "touchless_faders"), [1])
    assert doc.restart_sections == ()
    doc.set(("device", "name"), "Other")
    assert doc.restart_sections == ("device",)
    doc.add_section("mqtt")
    assert doc.restart_sections == ("device", "mqtt")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[device", "is not valid TOML"),
        ("device = 3", "device is not a table ([device]), fix that in a text editor first"),
        ("strip = 3", "strip is not a list of tables ([[strip]])"),
        ("strip = [1, 2]", "strip is not a list of tables ([[strip]])"),
        ("layout = 3", "layout is not a list of tables with lists of tables ([[layout]], [[layout.strip]])"),
        ("[[layout]]\nstrip = 3", "layout is not a list of tables with lists of tables"),
    ],
)
def test_a_file_the_editor_can_not_edit_is_an_error(text: str, message: str):
    with pytest.raises(ConfigError, match=re.escape(message)):
        document(text)


def test_a_file_that_can_not_be_read_is_an_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="can't read"):
        ConfigDocument.open(tmp_path)


def test_a_strip_knows_its_type():
    assert StripDraft({"type": "auto"}).type == "auto"
    assert StripDraft({}).type is None


def test_an_optional_section_can_be_added_and_removed():
    doc = document()
    assert not doc.has_section("mqtt")
    with pytest.raises(KeyError, match=r"\[mqtt\] is not there, add it first"):
        doc.set(("mqtt", "host"), "broker")

    doc.add_section("mqtt")
    # without its required options it is a problem, not missing
    assert doc.validate().problems == [Problem(("mqtt", "host"), "Field required", "missing")]
    doc.set(("mqtt", "host"), "broker")
    doc.set(("mqtt", "password_file"), "~/.mqtt-password")
    doc.add_strip("homeassistant")
    doc.add_section("mqtt")

    text = doc.render()

    assert text.endswith(
        '[[strip]]\ntype = "homeassistant"\n\n[mqtt]\nhost = "broker"\npassword_file = "~/.mqtt-password"\n'
    )
    assert doc.validate().config is not None

    doc.remove_section("mqtt")
    assert "[mqtt]" not in doc.render()
    assert doc.validate().problems == [Problem((), "strips in Home Assistant need an [mqtt] section", "value_error")]


def test_a_removed_section_leaves_the_file():
    doc = document('[mqtt]\nhost = "broker"\n')
    assert doc.has_section("mqtt")

    doc.remove_section("mqtt")

    assert doc.render() == ""


def test_only_optional_sections_can_be_removed():
    with pytest.raises(AssertionError, match=r"\[device\] is not optional"):
        document().remove_section("device")


def test_a_strip_knows_whether_it_changed():
    doc = document()
    assert not any(doc.strip_changed(index) for index in range(8))

    doc.set(("strip", 1, "label"), "Web")
    doc.add_strip("auto")
    assert [doc.strip_changed(index) for index in range(5)] == [False, True, False, True, False]

    doc = document()
    doc.move_strip(0, 2)
    doc.remove_strip(2)
    assert [doc.strip_changed(index) for index in range(4)] == [True, True, True, False]


def test_the_saved_configuration_is_known():
    doc = document()
    assert doc.saved_config == parse_config(FILE)
    doc.set(("behavior", "max_volume"), 110)
    # the one in the file, not the edited one
    assert doc.saved_config == parse_config(FILE)
    assert document('[[strip]]\ntype = "fader"\n').saved_config is None


def test_a_state_can_be_restored():
    doc = document()
    state = doc.state()
    doc.remove_strip(0)
    doc.aliases.append(("Brave", "Web"))
    doc.add_section("mqtt")

    doc.restore(state)

    assert doc.render() == FILE
    # the state stays as it was for another restore
    doc.remove_strip(0)
    doc.restore(state)
    assert len(doc.strips) == 3


LAYOUTS = """\
[[strip]]
type = "output"   # the speakers
label = "Speaker"

[voip]
provider = "demo"

# the games
[[layout]]
name = "gaming"   # for games
apps = ["steam_app_"]

[[layout.strip]]
type = "inherit"

[[layout.strip]]
type = "voip"  # people
count = 2

# for music
[[layout]]
name = "music"

[[layout.strip]]
type = "apps"
label = "Player"
match = ["spotify"]
"""


def test_layouts_are_read_and_written_as_they_were():
    doc = document(LAYOUTS)

    assert doc.render() == LAYOUTS
    assert doc.layout_names == ["default", "gaming", "music"]
    assert (doc.layout, doc.layout_name) == (None, "default")
    assert [strip.type for strip in doc.strips] == ["output"]
    assert doc.validate().problems == []
    # what the daemon reads
    assert doc.data()["layout"] == tomllib.loads(LAYOUTS)["layout"]


def test_the_first_layout_goes_after_the_strips():
    doc = document(FILE)
    doc.add_layout()
    doc.add_strip("voip")

    text = doc.render()

    assert text.startswith(FILE)
    assert tomllib.loads(text)["layout"] == [{"name": "layout_2", "strip": [{"type": "voip"}]}]


def test_the_strips_of_another_layout_are_edited():
    doc = document(LAYOUTS)
    doc.edit_layout(0)

    assert doc.layout_name == "gaming"
    assert [strip.type for strip in doc.strips] == ["inherit", "voip"]
    doc.set(("layout", "label"), "Gaming")
    doc.set(("strip", 1, "count"), 3)
    doc.add_strip("input")
    assert doc.get(("layout", "apps")) == ["steam_app_"]

    text = doc.render()
    assert 'name = "gaming"   # for games\napps = ["steam_app_"]\nlabel = "Gaming"\n' in text
    assert 'type = "voip"  # people\ncount = 3\n' in text
    assert tomllib.loads(text)["layout"][0]["strip"][2] == {"type": "input"}
    # the default layout stays as it was
    assert tomllib.loads(text)["strip"] == [{"type": "output", "label": "Speaker"}]
    assert [doc.strip_changed(index) for index in range(4)] == [False, True, True, False]

    doc.edit_layout(None)
    assert [strip.type for strip in doc.strips] == ["output"]
    with pytest.raises(IndexError):
        doc.edit_layout(2)
    # the default layout has no options of its own
    with pytest.raises(KeyError):
        doc.get(("layout", "name"))


def test_layouts_can_be_added_removed_and_moved():
    doc = document(LAYOUTS)
    doc.edit_layout(1)

    assert doc.add_layout(copy_strips=True) == 2
    assert doc.layout_names == ["default", "gaming", "music", "layout_2"]
    assert [strip.values for strip in doc.strips] == [{"type": "apps", "label": "Player", "match": ["spotify"]}]
    # a copy: the strips of music stay
    doc.set(("strip", 0, "label"), "Tunes")
    assert doc.layouts[1].strips[0].values["label"] == "Player"
    assert doc.add_layout() == 3
    assert doc.layout_name == "layout_3"
    assert doc.strips == []
    assert not doc.strip_changed(0)

    data = tomllib.loads(doc.render())
    assert data["layout"][2:] == [
        {"name": "layout_2", "strip": [{"type": "apps", "label": "Tunes", "match": ["spotify"]}]},
        {"name": "layout_3"},
    ]

    doc.move_layout(1, 0)
    assert doc.layout == 0
    assert doc.layout_names == ["default", "music", "gaming", "layout_2", "layout_3"]
    text = doc.render()
    # the comments go along
    assert text.index('name = "music"') < text.index('name = "gaming"   # for games')
    assert 'type = "voip"  # people' in text

    for _ in range(4):
        doc.remove_layout(0)
        assert doc.layout is None
    assert "layout" not in doc.render()
    assert doc.render().startswith('[[strip]]\ntype = "output"   # the speakers')


def test_problems_of_layouts_have_the_paths_of_the_editor():
    doc = document(LAYOUTS)
    doc.set(("strip", 0, "label"), "toolong12")
    doc.edit_layout(1)
    doc.set(("strip", 0, "label"), "toolong12")
    doc.set(("layout", "priority"), "high")
    doc.edit_layout(0)
    doc.set(("strip", 1, "count"), 9)

    validation = doc.validate()

    assert sorted(str(problem.path) for problem in validation.problems) == sorted(
        str(path)
        for path in (
            ("layouts", "default", "strip", 0, "label"),
            ("layouts", "music", "priority"),
            ("layouts", "music", "strip", 0, "label"),
            ("strip", 1, "count"),
        )
    )
    assert doc.layout_problems(validation, "gaming") == 1
    assert doc.layout_problems(validation, "music") == 2
    assert doc.layout_problems(validation, "default") == 1


def test_the_option_problems_of_the_edited_layout_start_with_layout():
    doc = document(LAYOUTS)
    doc.edit_layout(1)
    doc.set(("layout", "name"), "default")

    (problem,) = doc.validate().problems

    assert problem.path == ()
    assert "default" in problem.message
    doc.set(("layout", "name"), "Music!")
    (problem,) = doc.validate().problems
    assert problem.path == ("layout", "name")
    assert doc.layout_names[2] == "Music!"


def test_a_layout_without_a_name_has_an_empty_one():
    doc = document("[[layout]]\nname = 3\n")
    assert doc.layout_names == ["default", ""]


def test_the_state_and_the_file_keep_the_layouts(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(LAYOUTS)
    doc = ConfigDocument.open(path)
    doc.edit_layout(1)
    state = doc.state()
    doc.remove_layout(1)
    doc.restore(state)
    assert (doc.layout, doc.layout_names) == (1, ["default", "gaming", "music"])

    doc.set(("layout", "label"), "Music")
    doc.save()
    assert doc.layout == 1
    assert 'label = "Music"' in path.read_text()

    doc.remove_layout(1)
    doc.revert()
    assert doc.layout is None
    assert doc.layout_names == ["default", "gaming", "music"]
    doc.edit_layout(0)
    doc.revert()
    assert doc.layout == 0
