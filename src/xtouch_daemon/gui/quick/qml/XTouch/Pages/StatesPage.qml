// The page States: the modes and states in a list on the left (a dot for what the daemon says now; Add, Duplicate and
// Remove under it), and on the right what the one picked is, with its sources or its condition, its delays and what the
// daemon says about it. The two panes have a handle that keeps its place.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

Item {
    id: page
    required property QtObject app
    readonly property QtObject states: app.states
    readonly property alias list: list
    objectName: "states_page"

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: Theme.space.s
        spacing: Theme.space.s

        SectionHeader {
            text: "States"
            Layout.leftMargin: Theme.space.m
        }
        SlotFadeText {
            objectName: "states_hint"
            markup: page.states.tools.help(page.states.hint, Theme.mode, page.states.hintLink, "")
            Layout.fillWidth: true
            Layout.leftMargin: Theme.space.m
            Layout.rightMargin: Theme.space.l
        }

        PaneSplit {
            id: split
            objectName: "state_panes"
            Layout.fillWidth: true
            Layout.fillHeight: true
            share: page.states.pane.share
            onMoved: share => page.states.pane.share = share
            onReleased: page.states.pane.keep()

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space.s
                    spacing: Theme.space.s
                    EntryList {
                        id: list
                        objectName: "state_list"
                        model: page.states.entries
                        current: page.states.current
                        currentRow: page.states.currentIndex
                        entity: "state"
                        // the dot after the name: filled while on, a ring while off, none without a daemon
                        trailing: Component {
                            SlotDot {
                                property var row: ({})
                                objectName: "dot"
                                visible: row.dot !== null && row.dot !== undefined
                                on: row.dot === true
                                hue: Theme.colors.state
                            }
                        }
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        onPicked: key => page.states.pick(key)
                        onStepped: direction => page.states.step(direction)
                        onActiveFocusChanged: page.states.listFocus(activeFocus)
                    }
                    EntryButtons {
                        id: buttons
                        canDuplicate: !(page.states.inspector.empty ?? true)
                        canRemove: !(page.states.inspector.empty ?? true)
                        removeTip: "Remove the state or mode (Del)"
                        onAddClicked: addMenu.toggle()
                        onDuplicateClicked: page.states.duplicate()
                        onRemoveClicked: page.states.remove()
                    }
                }
            }

            StateInspector {
                id: inspector
                states: page.states
                onSlotPicked: slot => {
                    page.app.slots.selectSlot(slot)
                    page.app.showPage("slots")
                }
            }
        }
    }

    ActionMenu {
        id: addMenu
        objectName: "state_add_menu"
        anchor: buttons.addButton
        onAboutToShow: sections = page.states.addEntries()
        onTriggered: action => page.states.add(action)
    }

    Connections {
        target: page.states
        function onRenameRequested() {
            inspector.renameId()
        }
    }
}
