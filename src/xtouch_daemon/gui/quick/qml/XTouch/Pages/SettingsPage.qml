// The page Settings (a stub of the foundation: its part of the migration fills it in).
import QtQuick
import QtQuick.Controls
import XTouch

Item {
    required property QtObject app
    Label { anchors.centerIn: parent; text: "Settings"; color: Theme.colors.text_muted }
}
