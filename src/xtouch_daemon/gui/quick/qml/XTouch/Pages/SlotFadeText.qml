// A text that wraps and fades through when it changes (the old one out, then the new one in); its height moves to
// the new one. `markup` is rich text that names theme colors as `@state` (see `slots_data.rich`).
import QtQuick
import XTouch

Item {
    id: fadeText
    property string markup
    property string text
    property color color: Theme.colors.text_muted
    property bool bold: false
    property int textFormat: markup !== "" ? Text.RichText : Text.PlainText
    property int wrapMode: Text.Wrap
    property real pointSize: Theme.fontSize.caption
    readonly property string resolved: markup !== "" ? resolve(markup) : text

    implicitHeight: shown.implicitHeight
    implicitWidth: shown.implicitWidth
    Behavior on implicitHeight { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }

    function resolve(m) {
        // a link in rich text takes its color from its own style, not from linkColor
        const link = "<a style=\"color: " + Theme.colors.accent + "\" href="
        return m.replace(/<a href=/g, link)
            .replace(/@([a-z_]+)/g, (all, name) => Theme.colors[name] !== undefined ? String(Theme.colors[name]) : all)
    }

    Text {
        id: old
        width: fadeText.width
        font: shown.font
        color: fadeText.color
        opacity: 0
        wrapMode: fadeText.wrapMode
        textFormat: fadeText.textFormat
    }
    Text {
        id: shown
        width: fadeText.width
        text: fadeText.resolved
        color: fadeText.color
        font.pointSize: fadeText.pointSize
        font.bold: fadeText.bold
        wrapMode: fadeText.wrapMode
        textFormat: fadeText.textFormat
        linkColor: Theme.colors.accent
        onLinkActivated: link => Qt.openUrlExternally(link)
        HoverHandler { cursorShape: shown.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
    }
    property string previous: resolved
    onResolvedChanged: {
        if (Theme.fade > 0 && previous !== "" && previous !== resolved && resolved !== "") {
            old.text = previous
            through.restart()
        }
        previous = resolved
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
