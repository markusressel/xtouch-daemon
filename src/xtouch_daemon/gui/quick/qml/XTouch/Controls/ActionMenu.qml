// A menu inside the window (a popover): groups of entries under a title each, an entry with its icon, its text and a
// line under it that says what it does (rich text that names theme colors as `@channel`). An entry with `children` opens
// them under it instead of acting; one that is not `enabled` is dimmed. `sections` is
// `[{title, items: [{action, text, icon, detail, enabled, children}]}]`; `triggered(action)` says which one was picked,
// and the menu closes. The page opens it from its button (`open()`) and fills `sections` in `aboutToShow`.
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.impl
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Popover {
    id: menu
    property var sections: []
    signal triggered(string action)

    preferredWidth: 380

    function resolve(markup) {
        return markup.replace(/@([a-z_]+)/g, (all, name) => Theme.colors[name] !== undefined ? String(Theme.colors[name]) : all)
    }

    Flickable {
        id: scroll
        // an item that opens (the devices) stays in view
        function keep(item) {
            Qt.callLater(() => {
                const bottom = item.mapToItem(column, 0, item.height).y
                if (bottom > contentY + height) contentY = Math.min(column.height - height, bottom - height)
            })
        }
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(column.height, 460)
        contentHeight: column.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { }

        Column {
            id: column
            width: scroll.width
            spacing: Theme.space.xs

            Repeater {
                model: menu.sections
                Column {
                    id: group
                    required property var modelData
                    width: column.width
                    Label {
                        text: group.modelData.title
                        font.bold: true
                        font.pointSize: Theme.fontSize.caption
                        color: Theme.colors.text_muted
                        topPadding: Theme.space.xs
                        bottomPadding: Theme.space.xs
                        leftPadding: Theme.space.s
                    }
                    Repeater {
                        model: group.modelData.items
                        Column {
                            id: item
                            required property var modelData
                            property bool open: false
                            readonly property bool enabledItem: modelData.enabled !== false
                            width: group.width
                            objectName: "menu_" + (modelData.action !== "" ? modelData.action : modelData.text)

                            ItemDelegate {
                                id: delegate
                                width: parent.width
                                enabled: item.enabledItem
                                padding: Theme.space.s
                                onClicked: {
                                    if (item.modelData.children !== undefined) {
                                        item.open = !item.open
                                    } else {
                                        menu.close()
                                        menu.triggered(item.modelData.action)
                                    }
                                }
                                contentItem: RowLayout {
                                    spacing: Theme.space.s
                                    IconImage {
                                        source: item.modelData.icon ? "image://icon/" + item.modelData.icon : ""
                                        sourceSize: Qt.size(18, 18)
                                        color: Theme.colors.channel
                                        Layout.alignment: Qt.AlignTop
                                        Layout.preferredWidth: 18
                                        Layout.preferredHeight: 18
                                    }
                                    ColumnLayout {
                                        spacing: 0
                                        Layout.fillWidth: true
                                        Label {
                                            text: item.modelData.text
                                            font.bold: true
                                            color: item.enabledItem ? Theme.colors.text : Theme.colors.text_muted
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }
                                        Text {
                                            visible: item.modelData.detail !== undefined && item.modelData.detail !== ""
                                            text: menu.resolve(item.modelData.detail ?? "")
                                            textFormat: Text.RichText
                                            wrapMode: Text.Wrap
                                            color: Theme.colors.text_muted
                                            font.pointSize: Theme.fontSize.caption
                                            Layout.fillWidth: true
                                        }
                                    }
                                    IconImage {
                                        visible: item.modelData.children !== undefined
                                        source: "image://icon/chevron-down"
                                        sourceSize: Qt.size(18, 18)
                                        color: Theme.colors.text_muted
                                        rotation: item.open ? 180 : 0
                                        Behavior on rotation { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
                                        Layout.alignment: Qt.AlignTop
                                    }
                                }
                            }
                            Reveal {
                                id: submenu
                                width: parent.width
                                shown: item.open && item.modelData.children !== undefined
                                onHeightChanged: if (item.open) scroll.keep(submenu)
                                Column {
                                    width: parent.width
                                    leftPadding: Theme.space.l
                                    Repeater {
                                        model: item.modelData.children ?? []
                                        ItemDelegate {
                                            required property var modelData
                                            objectName: "menu_" + modelData.action
                                            width: parent.width - Theme.space.l
                                            padding: Theme.space.s
                                            onClicked: {
                                                menu.close()
                                                menu.triggered(modelData.action)
                                            }
                                            contentItem: ColumnLayout {
                                                spacing: 0
                                                Label {
                                                    text: modelData.text
                                                    font.bold: true
                                                    elide: Text.ElideRight
                                                    Layout.fillWidth: true
                                                }
                                                Text {
                                                    text: menu.resolve(modelData.detail ?? "")
                                                    textFormat: Text.RichText
                                                    wrapMode: Text.Wrap
                                                    color: Theme.colors.text_muted
                                                    font.pointSize: Theme.fontSize.caption
                                                    Layout.fillWidth: true
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
