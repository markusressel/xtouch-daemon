// PLACEHOLDER for the option rows of the parts an entry of the controls of a slot sets (Fader, Encoder, Select, Rec,
// Solo, Meter, Color, LCD line, and Id). The forms part (`XTouch.Forms`) replaces this item with its generic
// option rows. What it gets:
//   - `optionPath`: where the entry is in the document, e.g. ["controls", "3"] or ["controls", "3", 1] for the
//     second entry of a list; the option of a part `name` is at [..., "name"];
//   - `parts`: the parts the entry sets, each `{name, title}` (the title as the device names the part);
//   - `hasId`: whether the row `id` shows (set, or the entry uses Home Assistant);
//   - `controls`: the backend: `put(path, value)` edits (null removes), see `slots_controls.py`.
// A part removed (its reset button) goes back to what the slot shows.
import QtQuick
import XTouch

Item {
    id: parts
    objectName: "controls_parts_placeholder"
    required property QtObject controls
    property int entryIndex: 0
    property var optionPath: []
    property var parts: []
    property bool hasId: false

    implicitHeight: 0
    height: implicitHeight
}
