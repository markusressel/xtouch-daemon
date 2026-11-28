// The footer of the window (a stub of the foundation: the window's part of the migration fills it in).
import QtQuick
import QtQuick.Controls
import XTouch

Rectangle {
    required property QtObject app
    implicitHeight: Theme.controlHeight + Theme.space.s
    color: Theme.colors.chrome
    Rectangle { width: parent.width; height: 1; color: Theme.colors.border }
}
