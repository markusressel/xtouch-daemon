// The page Channels: the channels and pools in a list on the left (Add, Duplicate, Remove under it), and on the right
// what the one picked is: its id, where it is used, and its form. The two panes have a handle that keeps its place.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls
import XTouch.Slots

Item {
    id: page
    required property QtObject app
    readonly property QtObject channels: app.channels
    readonly property alias list: list
    objectName: "channels_page"

    Component.onCompleted: channels.prebuild()

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: Theme.space.s
        spacing: Theme.space.s

        SectionHeader {
            text: "Channels"
            Layout.leftMargin: Theme.space.m
        }
        SlotFadeText {
            objectName: "channels_hint"
            markup: page.channels.tools.help(page.channels.inspector.hint ?? "", Theme.mode, page.channels.inspector.startLink ?? "", "")
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.m
            Layout.rightMargin: Theme.space.l
        }
        Reveal {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.m
            Layout.rightMargin: Theme.space.l
            shown: (page.channels.inspector.start ?? "") !== ""
            SlotFadeText {
                objectName: "channels_start"
                width: parent.width
                markup: page.channels.tools.help(page.channels.inspector.start ?? "", Theme.mode, "", "")
            }
        }

        PaneSplit {
            id: split
            objectName: "channel_panes"
            Layout.fillWidth: true
            Layout.fillHeight: true
            share: page.channels.pane.share
            onMoved: share => page.channels.pane.share = share
            onReleased: page.channels.pane.keep()

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space.s
                    spacing: Theme.space.s
                    EntryList {
                        id: list
                        objectName: "channel_list"
                        model: page.channels.entries
                        current: page.channels.current
                        currentRow: page.channels.currentIndex
                        entity: "channel"
                        trailing: Component {
                            SoundBadge {
                                property var row: ({})
                                objectName: "sound"
                                visible: row.sound !== ""
                                channel: row.sound
                                kind: row.soundKind
                                hue: Theme.colors.channel
                            }
                        }
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        onPicked: key => page.channels.pick(key)
                        onStepped: direction => page.channels.step(direction)
                        onActiveFocusChanged: page.channels.listFocus(activeFocus)
                    }
                    EntryButtons {
                        id: buttons
                        canDuplicate: page.channels.inspector.mine ?? false
                        canRemove: page.channels.inspector.mine ?? false
                        removeTip: "Remove the channel or pool (Del)"
                        onAddClicked: addMenu.open()
                        onDuplicateClicked: page.channels.duplicate()
                        onRemoveClicked: page.channels.remove()
                    }
                }
            }

            ChannelInspector {
                id: inspector
                channels: page.channels
                onSlotPicked: slot => {
                    page.app.slots.selectSlot(slot)
                    page.app.showPage("slots")
                }
            }
        }
    }

    ActionMenu {
        id: addMenu
        objectName: "channel_add_menu"
        anchor: buttons.addButton
        onAboutToShow: sections = page.channels.addEntries()
        onTriggered: action => page.channels.add(action)
    }

    Connections {
        target: page.channels
        function onRenameRequested() {
            inspector.renameId()
        }
    }
}
