// A list that is as high as its rows, whose rows grow in and fade out while the ones under them slide along.
import QtQuick
import XTouch

ListView {
    id: list
    interactive: false
    implicitHeight: contentHeight
    height: contentHeight
    Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }

    add: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Theme.resize; easing.type: Easing.OutCubic }
    }
    remove: Transition {
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.fade }
    }
    displaced: Transition {
        NumberAnimation { properties: "y"; duration: Theme.resize; easing.type: Easing.OutCubic }
    }
}
