// The dot of a crumb or a state: filled while `on`, a ring while not. A shape, not a character: a font puts a
// bullet wherever its glyph sits.
import QtQuick
import XTouch

Rectangle {
    id: dot
    property bool on: true
    property color hue: Theme.colors.text
    property real size: 8
    implicitWidth: size
    implicitHeight: size
    width: size
    height: size
    radius: size / 2
    color: on ? hue : "transparent"
    border.width: on ? 0 : 1.5
    border.color: hue
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    Behavior on border.color { ColorAnimation { duration: Theme.fade } }
}
