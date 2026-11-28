// The drawing of the device (a stub of the foundation: the device's part of the migration fills it in).
import QtQuick
import QtQuick.Controls
import XTouch

Rectangle {
    required property QtObject app
    color: Theme.colors.surface
    Label { anchors.centerIn: parent; text: "Device"; color: Theme.colors.text_muted }
}
