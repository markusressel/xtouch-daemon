// The page Settings: a navigation of the sections of the configuration with options of their own, and the page of the
// one picked, which fades through to the next. The Home Assistant entry shows two sections, the MQTT broker and the API.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: page
    required property QtObject app
    readonly property QtObject settings: app.settings
    readonly property alias nav: nav

    objectName: "page_settings"

    Rectangle {
        id: nav
        objectName: "settings_nav"
        width: 200
        height: parent.height
        color: "transparent"

        Rectangle {
            id: mark
            readonly property Item target: column.children[page.settings.entries.findIndex(entry => entry.name === page.settings.current)] ?? null
            x: Theme.space.s
            y: column.y + (target ? target.y : 0)
            width: target ? target.width : 0
            height: target ? target.height : 0
            radius: Theme.radius.medium
            color: Theme.colors.accent_tint
            Behavior on y { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
        }

        Column {
            id: column
            x: Theme.space.s
            y: Theme.space.m
            width: parent.width - 2 * Theme.space.s
            spacing: Theme.space.xs
            Repeater {
                model: page.settings.entries
                ToolButton {
                    required property var modelData
                    objectName: "settings_nav_" + modelData.name
                    width: column.width
                    text: modelData.title
                    horizontalPadding: Theme.space.m
                    contentItem: Label {
                        text: parent.text
                        color: page.settings.current === modelData.name ? Theme.colors.text : Theme.colors.text_muted
                        font.bold: page.settings.current === modelData.name
                        verticalAlignment: Text.AlignVCenter
                        Behavior on color { ColorAnimation { duration: Theme.fade } }
                    }
                    background: Item {}
                    onClicked: page.settings.showSection(modelData.name)
                }
            }
        }

        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.colors.border }
    }

    Item {
        id: content
        anchors { left: nav.right; right: parent.right; top: parent.top; bottom: parent.bottom }

        Repeater {
            model: page.settings.entries
            Loader {
                id: holder
                required property var modelData
                readonly property bool current: page.settings.current === modelData.name
                // a page is made when it is picked first, then kept
                property bool visited: false
                onCurrentChanged: if (current) visited = true
                Component.onCompleted: if (current) visited = true
                objectName: "settings_page_" + modelData.name
                anchors.fill: parent
                active: visited
                opacity: current ? 1 : 0
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: Theme.fade; easing.type: Easing.InOutQuad } }
                sourceComponent: modelData.name === "aliases" ? aliases : modelData.name === "mqtt" ? home : modelData.name === "voip" ? voip : plain

                Component {
                    id: plain
                    SettingsSection { app: page.app; section: page.settings.sections[holder.modelData.name] }
                }
                Component {
                    id: home
                    SettingsSection {
                        app: page.app
                        section: page.settings.sections.mqtt
                        second: page.settings.sections.homeassistant
                    }
                }
                Component {
                    id: voip
                    SettingsSection { app: page.app; section: page.settings.sections.voip; plugins: true }
                }
                Component { id: aliases; AliasesPane { app: page.app } }
            }
        }
    }
}
