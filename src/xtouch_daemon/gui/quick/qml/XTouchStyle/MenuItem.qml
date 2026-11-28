// An entry of a menu: its icon, its text and its shortcut; `description` puts a line under it that says what it does.
import QtQuick
import QtQuick.Controls.impl
import QtQuick.Templates as T
import QtQuick.Layouts
import XTouch

T.MenuItem {
    id: control
    property string description: ""
    readonly property string shortcutText: action && action.shortcut ? String(action.shortcut) : ""

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                            implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding,
                             implicitIndicatorHeight + topPadding + bottomPadding)
    padding: Theme.space.xs
    horizontalPadding: Theme.space.s
    spacing: Theme.space.s
    icon.width: 18
    icon.height: 18
    hoverEnabled: true

    contentItem: RowLayout {
        spacing: control.spacing
        Item {
            implicitWidth: 18
            implicitHeight: 18
            ColorImage {
                anchors.fill: parent
                visible: control.checkable ? control.checked : control.icon.source.toString() !== ""
                source: control.checkable ? "image://icon/check" : control.icon.source
                color: control.enabled ? Theme.colors.text : Theme.colors.text_muted
            }
        }
        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            Text {
                text: control.text
                font: control.font
                color: control.enabled ? Theme.colors.text : Theme.colors.text_muted
            }
            Text {
                visible: control.description !== ""
                text: control.description
                font.pointSize: Theme.fontSize.caption
                color: Theme.colors.text_muted
                Layout.maximumWidth: 320
                wrapMode: Text.Wrap
            }
        }
        Text {
            visible: control.shortcutText !== ""
            text: control.shortcutText
            font: control.font
            color: Theme.colors.text_muted
            Layout.leftMargin: Theme.space.l
        }
        ColorImage {
            visible: control.subMenu !== null
            source: "image://icon/chevron-right"
            width: 16; height: 16
            color: Theme.colors.text_muted
        }
    }

    background: Rectangle {
        implicitWidth: 200
        implicitHeight: Theme.controlHeight
        radius: Theme.radius.small
        color: control.down ? Theme.tint(Theme.colors.text, 0.16)
            : control.highlighted ? Theme.colors.accent_tint : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.fade } }
    }
}
