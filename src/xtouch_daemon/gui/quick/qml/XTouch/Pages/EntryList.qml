// The list of the entries of a page (channels and pools, states and modes): a title of a group, or an entry with its
// icon, its name in the color of what it is (`entity`), a line under it, a mark for a problem and what `trailing`
// adds (the sound of a channel, the dot of a state). The `model` is a `KeyedListModel`: its rows are
// `{kind, name, title, tags, below (rich text), icon, tip, problem, ...}`, `kind` `header` for a title. Rows come, go
// and slide along as the list changes, the mark of the entry picked glides to the next one, and a rename fades through.
// The arrow keys step through the entries (`stepped`), a click picks one (`picked`).
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import XTouch
import XTouch.Controls

ListView {
    id: list
    // the key of the entry picked, and its row
    property string current
    property int currentRow: -1
    property string entity: "channel"
    // what goes at the right of an entry: an item with a `row` (its values)
    property Component trailing: null
    signal picked(string key)
    signal stepped(int direction)

    clip: true
    boundsBehavior: Flickable.StopAtBounds
    activeFocusOnTab: true
    currentIndex: currentRow
    highlightMoveDuration: Theme.resize
    highlightResizeDuration: Theme.resize
    highlightFollowsCurrentItem: true
    ScrollBar.vertical: ScrollBar { }

    Keys.onUpPressed: list.stepped(-1)
    Keys.onDownPressed: list.stepped(1)

    highlight: Rectangle {
        radius: Theme.radius.medium
        color: Theme.colors.accent_tint
        border.width: list.activeFocus ? 1 : 0
        border.color: Theme.colors.accent
    }

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

    delegate: Item {
        id: entry
        required property var row
        required property string key
        required property int index
        readonly property bool header: row.kind === "header"
        readonly property color hue: Theme.colors[list.entity] !== undefined ? Theme.colors[list.entity] : Theme.colors.text

        objectName: header ? "header_" + key : "entry_" + key
        width: ListView.view.width
        height: header ? headerText.implicitHeight + Theme.space.m + Theme.space.xs : body.implicitHeight + 2 * Theme.space.s

        Label {
            id: headerText
            visible: entry.header
            x: Theme.space.s
            y: Theme.space.m
            width: parent.width - 2 * Theme.space.s
            text: entry.row.title
            font.bold: true
            font.pointSize: Theme.fontSize.caption
            color: Theme.colors.text_muted
            elide: Text.ElideRight
        }

        Rectangle {
            visible: !entry.header
            anchors.fill: parent
            anchors.margins: 1
            radius: Theme.radius.medium
            color: Theme.tint(Theme.colors.text, 0.07)
            opacity: hover.hovered && list.current !== entry.key ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.fade } }
        }

        RowLayout {
            id: body
            visible: !entry.header
            x: Theme.space.s
            y: Theme.space.s
            width: parent.width - 2 * Theme.space.s
            spacing: Theme.space.s

            IconImage {
                source: entry.header || entry.row.icon === "" ? "" : "image://icon/" + entry.row.icon
                sourceSize: Qt.size(18, 18)
                color: entry.hue
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                RowLayout {
                    spacing: Theme.space.xs
                    Layout.fillWidth: true
                    FadeText {
                        objectName: "title"
                        text: entry.row.title
                        color: entry.hue
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                        Layout.maximumWidth: Math.ceil(implicitWidth) + 1
                    }
                    Label {
                        visible: entry.row.tags !== ""
                        text: entry.row.tags
                        color: Theme.colors.text_muted
                        font.pointSize: Theme.fontSize.caption
                        elide: Text.ElideRight
                    }
                    Item { Layout.fillWidth: true }
                }
                SlotFadeText {
                    objectName: "below"
                    markup: entry.row.below
                    Layout.fillWidth: true
                }
            }
            Loader {
                active: list.trailing !== null && !entry.header
                sourceComponent: list.trailing
                Layout.alignment: Qt.AlignTop
                onLoaded: item.row = Qt.binding(() => entry.row)
            }
            IconImage {
                objectName: "problem"
                source: "image://icon/alert-outline"
                sourceSize: Qt.size(16, 16)
                color: Theme.colors.error
                opacity: entry.row.problem ? 1 : 0
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: Theme.fade } }
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 16
                Layout.preferredHeight: 16
            }
        }

        HoverHandler { id: hover; enabled: !entry.header }
        ToolTip.visible: hover.hovered && !entry.header && entry.row.tip !== ""
        ToolTip.text: entry.row.tip
        ToolTip.delay: 600
        MouseArea {
            anchors.fill: parent
            enabled: !entry.header
            onPressed: {
                list.picked(entry.key)
                list.forceActiveFocus(Qt.MouseFocusReason)
            }
        }
    }
}
