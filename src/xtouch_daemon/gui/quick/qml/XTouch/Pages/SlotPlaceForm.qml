// PLACEHOLDER for the form of the options of the place of the candidate picked ("Look in slot N": the color, the
// encoder, the meter, ... of this candidate only). The forms part (`XTouch.Forms`) replaces this item with its
// generic option rows. What it gets:
//   - `optionPath`: where the options are in the document, e.g. ["slots", "2", 0] (slot 2, candidate 0); an option
//     `name` of it is at [..., "name"];
//   - `strip`: the type of strip the place is for (`apps`, `auto`, `output`, `voip`, ...), `allowed`: the names of
//     the options it takes, `pick`: whether the encoder may pick (a choice of the option `encoder`);
//   - `slots`: the backend, with `placeOption(name)`, `setPlaceOption(name, value)` (null unsets),
//     `placeInherited(name)` (the placeholder of an unset option: what it takes from its channel or pool) and
//     `placeHelp(name)` (its help, rich text).
// Every option is optional here: unset, it is as on the channel or in the pool.
import QtQuick
import XTouch

Item {
    id: form
    objectName: "place_form_placeholder"
    required property QtObject slots
    property var optionPath: []
    property string strip: ""
    property var allowed: []
    property bool pick: true

    implicitHeight: 0
    height: implicitHeight
}
