// The menus of the window (a stub of the foundation: the window's part of the migration fills it in).
import QtQuick
import QtQuick.Controls
import XTouch

Rectangle {
    required property QtObject app
    implicitHeight: Theme.controlHeight
    color: Theme.colors.chrome
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.colors.border }
}
