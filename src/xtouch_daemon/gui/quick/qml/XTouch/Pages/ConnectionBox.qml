// How the daemon's connection (to the broker, to the API) is doing, and a button that tries the settings as they are in
// the editor, also unsaved ones, once. Only the latest result shows.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls
import XTouch.Forms

Card {
    id: box
    required property QtObject section
    readonly property var view: section.live.view
    readonly property var tools: section.form.tools
    objectName: "connection_" + section.name

    Row {
        width: parent.width
        spacing: Theme.space.s
        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: "The daemon"
            color: Theme.colors.text_muted
        }
        Pill {
            objectName: "live_" + box.section.name
            anchors.verticalCenter: parent.verticalCenter
            text: box.view.live.text
            tone: box.view.live.tone
            ToolTip.visible: hovered && box.view.live.tip !== ""
            ToolTip.text: box.view.live.tip
        }
        Item { width: Math.max(0, parent.width - x - testButton.width - parent.spacing - 200); height: 1 }
        Button {
            id: testButton
            objectName: "test_" + box.section.name
            anchors.verticalCenter: parent.verticalCenter
            icon.source: "image://icon/lan-connect"
            text: "Test connection"
            enabled: !box.view.testing
            ToolTip.visible: hovered
            ToolTip.text: box.section.name === "homeassistant"
                ? "Connect once with the settings below, also unsaved ones, read the entities, and disconnect again"
                : "Connect once with the settings below, also unsaved ones, and disconnect again"
            onClicked: box.section.test()
        }
    }

    HelpLabel {
        objectName: "live_detail_" + box.section.name
        width: parent.width
        text: box.tools.help(box.view.live.tip, Theme.mode, "", "")
    }

    Reveal {
        width: parent.width
        shown: box.view.test !== null
        Column {
            width: parent.width
            spacing: Theme.space.xs
            Label {
                objectName: "test_result_" + box.section.name
                width: parent.width
                text: box.view.test ? box.view.test.text : ""
                wrapMode: Text.Wrap
                color: !box.view.test ? Theme.colors.text : box.view.test.tone === "bad" ? Theme.colors.error
                    : box.view.test.tone === "good" ? Theme.colors.text : Theme.colors.text_muted
            }
            HelpLabel {
                visible: !!box.view.test && (box.view.test.tip ?? "") !== ""
                width: parent.width
                text: box.view.test && box.view.test.tip ? box.tools.help(box.view.test.tip, Theme.mode, "", "") : ""
            }
        }
    }
}
