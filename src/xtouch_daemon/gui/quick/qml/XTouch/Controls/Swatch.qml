// A small square of a color, e.g. the backlight of an LCD.
import QtQuick
import XTouch

Rectangle {
    implicitWidth: 10
    implicitHeight: 10
    radius: 2
    border.color: Theme.colors.control_border
    Behavior on color { ColorAnimation { duration: Theme.fade } }
}
