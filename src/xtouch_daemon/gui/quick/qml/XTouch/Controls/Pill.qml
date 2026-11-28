// A pill: a short state in a tone (`good`, `warn`, `bad`, `neutral`, or `accent`), on a tint of it. With `clickable`
// it is a button (Tab reaches it, Space and Enter press it), e.g. to open a popover with the details.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import XTouch

AbstractButton {
    id: pill
    property string tone: "neutral"
    property bool clickable: false
    property string iconName: ""
    readonly property color hue: tone === "good" ? Theme.colors.tone_good : tone === "warn" ? Theme.colors.tone_warn
        : tone === "bad" ? Theme.colors.tone_bad : tone === "accent" ? Theme.colors.accent : Theme.colors.tone_neutral

    enabled: true
    focusPolicy: clickable ? Qt.StrongFocus : Qt.NoFocus
    hoverEnabled: clickable
    leftPadding: Theme.space.s
    rightPadding: Theme.space.s
    topPadding: 2
    bottomPadding: 2
    spacing: Theme.space.xs
    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    implicitHeight: Math.max(24, contentItem.implicitHeight + topPadding + bottomPadding)
    Accessible.role: clickable ? Accessible.Button : Accessible.StaticText

    contentItem: Row {
        spacing: pill.spacing
        ColorImage {
            visible: pill.iconName !== ""
            anchors.verticalCenter: parent.verticalCenter
            width: 14; height: 14
            source: pill.iconName !== "" ? "image://icon/" + pill.iconName : ""
            color: pill.hue
        }
        FadeText {
            anchors.verticalCenter: parent.verticalCenter
            text: pill.text
            color: pill.hue
            bold: true
        }
    }

    background: Rectangle {
        radius: Theme.radius.pill
        color: Theme.tint(pill.hue, pill.down ? 0.32 : pill.hovered ? 0.24 : 0.14)
        border.width: pill.visualFocus ? 2 : 0
        border.color: Theme.colors.accent
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }
}
