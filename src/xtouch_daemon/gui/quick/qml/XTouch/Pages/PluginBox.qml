// The plugin of a voice chat client: whether it is connected to the daemon, the steps to set it up, and a button that
// installs it (it is built first where needed, which takes a few seconds). A client that is not installed gets a line.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls
import XTouch.Forms

Card {
    id: card
    required property QtObject box
    readonly property var view: box.view
    objectName: "plugin_" + box.name.toLowerCase()

    // links in the colors of the theme: Qt paints the links of rich text blue
    function linked(html) { return html.replace(/<a /g, '<a style="color: ' + Theme.colors.accent + '" ') }

    Row {
        width: parent.width
        spacing: Theme.space.s
        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: card.view.name
            color: Theme.colors.text_muted
        }
        Pill {
            objectName: "plugin_pill_" + card.box.name.toLowerCase()
            anchors.verticalCenter: parent.verticalCenter
            text: card.view.pill.text
            tone: card.view.pill.tone
            ToolTip.visible: hovered && card.view.pill.tip !== ""
            ToolTip.text: card.view.pill.tip
        }
        Item { width: Math.max(0, parent.width - x - install.width - parent.spacing - 200); height: 1 }
        Button {
            id: install
            objectName: "install_" + card.box.name.toLowerCase()
            visible: !card.view.compact
            anchors.verticalCenter: parent.verticalCenter
            icon.source: "image://icon/download"
            text: "Install " + card.view.name + " plugin"
            enabled: card.view.installEnabled
            ToolTip.visible: hovered
            ToolTip.text: card.view.installTip
            onClicked: card.box.install()
        }
    }

    Reveal {
        width: parent.width
        shown: card.view.detail !== ""
        HelpLabel { width: parent.width; text: card.linked(card.view.detail) }
    }

    HelpLabel {
        objectName: "plugin_steps_" + card.box.name.toLowerCase()
        width: parent.width
        textFormat: Text.RichText
        text: card.linked(card.view.steps)
    }

    Reveal {
        width: parent.width
        shown: card.view.outcome !== null
        TextEdit {
            objectName: "plugin_result_" + card.box.name.toLowerCase()
            width: parent.width
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            text: card.view.outcome ? card.view.outcome.text : ""
            color: card.view.outcome && card.view.outcome.tone === "bad" ? Theme.colors.error : Theme.colors.text
            font: Qt.application.font
        }
    }
}
