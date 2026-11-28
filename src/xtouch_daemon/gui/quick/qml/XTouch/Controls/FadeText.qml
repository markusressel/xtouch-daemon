// A text that fades through when it changes: the old one fades out, then the new one in, so the two never show on top
// of each other. Its width moves to the new one.
import QtQuick
import XTouch

Item {
    id: fadeText
    property string text
    property color color: Theme.colors.text
    property bool bold: false
    property alias font: shown.font
    property int elide: Text.ElideNone
    property int textFormat: Text.PlainText

    implicitWidth: shown.implicitWidth
    implicitHeight: shown.implicitHeight
    Behavior on implicitWidth { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }

    Text {
        id: old
        width: fadeText.width
        font: shown.font
        color: fadeText.color
        opacity: 0
        elide: fadeText.elide
        textFormat: fadeText.textFormat
    }
    Text {
        id: shown
        width: fadeText.width
        text: fadeText.text
        color: fadeText.color
        font.bold: fadeText.bold
        elide: fadeText.elide
        textFormat: fadeText.textFormat
    }
    property string previous: text
    onTextChanged: {
        if (Theme.fade > 0 && previous !== "" && previous !== text) {
            old.text = previous
            through.restart()
        }
        previous = text
    }
    SequentialAnimation {
        id: through
        ParallelAnimation {
            NumberAnimation { target: old; property: "opacity"; from: 1; to: 0; duration: Theme.fade * 0.5 }
            NumberAnimation { target: shown; property: "opacity"; from: 0; to: 0; duration: Theme.fade * 0.5 }
        }
        NumberAnimation { target: shown; property: "opacity"; from: 0; to: 1; duration: Theme.fade }
    }
}
