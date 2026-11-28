// A note across a page or card, with a line in its tone at the left: `warn`, `bad`, `good` or `neutral`.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch

Rectangle {
    id: banner
    property string tone: "warn"
    property alias text: label.text
    default property alias actions: row.data
    readonly property color hue: tone === "good" ? Theme.colors.tone_good : tone === "bad" ? Theme.colors.tone_bad
        : tone === "neutral" ? Theme.colors.tone_neutral : Theme.colors.tone_warn

    implicitHeight: layout.implicitHeight + 2 * Theme.space.s
    implicitWidth: layout.implicitWidth + 2 * Theme.space.m
    radius: Theme.radius.small
    color: Theme.tint(hue, Theme.tintAlpha)
    Rectangle { width: 3; height: parent.height; color: banner.hue; radius: 1 }

    RowLayout {
        id: layout
        anchors.fill: parent
        anchors.leftMargin: Theme.space.m
        anchors.rightMargin: Theme.space.s
        spacing: Theme.space.s
        Label {
            id: label
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        Row { id: row; spacing: Theme.space.xs }
    }
}
