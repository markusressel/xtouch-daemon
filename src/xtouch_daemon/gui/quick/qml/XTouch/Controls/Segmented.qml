// A row of buttons of which one is checked, like the field of a choice. `items` is `[{value, text, checked, visible}]`:
// the one that is `checked` is filled (none while another thing is picked elsewhere), one that is not `visible` grows
// away. A click says `picked(value)`; the checked one follows `items`, so the page decides.
import QtQuick
import QtQuick.Controls
import XTouch

Row {
    id: segmented
    property var items: []
    signal picked(string value)

    spacing: Theme.space.xs

    Repeater {
        model: segmented.items
        Item {
            id: segment
            required property var modelData
            property bool shown: modelData.visible !== false
            // sideways: a button that comes and goes slides the others
            width: shown ? button.implicitWidth : 0
            height: button.implicitHeight
            visible: width > 0
            clip: true
            opacity: shown ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fade } }
            Behavior on width { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
            Button {
                id: button
                objectName: (segmented.objectName !== "" ? segmented.objectName + "_" : "segment_") + segment.modelData.value
                text: segment.modelData.text
                highlighted: segment.modelData.checked === true
                onClicked: segmented.picked(segment.modelData.value)
            }
        }
    }
}
