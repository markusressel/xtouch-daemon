// The right of the page Channels: what the channel or pool picked is (its type, its id, where it is used), and its form.
// A form is for every channel of its type, so another channel of the same type changes the form in place; one of
// another type cross-fades into the form of that type. Forms are made when they first show (or in the background,
// see `ChannelsPage.prebuild`) and kept.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls
import XTouch.Device
import XTouch.Forms

SlotScroll {
    id: pane
    required property QtObject channels
    readonly property var info: channels.inspector
    readonly property real inset: Theme.space.l
    readonly property QtObject shownForm: info.formKey ? channels.formOf(info.formKey) : null
    signal slotPicked(int slot)

    objectName: "channel_inspector"
    contentHeight: Math.max(height, content.height + Theme.space.s)

    function renameId() {
        idField.forceActiveFocus()
        idField.selectAll()
    }

    // another entry: what the inspector shows dips and comes back with the new one
    property string key: channels.current
    onKeyChanged: dip.restart()
    SequentialAnimation {
        id: dip
        NumberAnimation { target: column; property: "opacity"; to: 0.35; duration: Theme.fade * 0.4 }
        NumberAnimation { target: column; property: "opacity"; to: 1; duration: Theme.fade }
    }

    Item {
        id: content
        x: Theme.space.s
        y: Theme.space.s
        width: pane.width - Theme.space.s - pane.inset
        height: column.height

        Column {
            id: column
            width: parent.width
            spacing: Theme.space.m

            RowLayout {
                width: parent.width
                spacing: Theme.space.m
                FadeText {
                    objectName: "channel_title"
                    text: pane.info.title ?? ""
                    font.pointSize: Theme.fontSize.section
                    font.bold: true
                    color: Theme.colors.text
                }
                TextField {
                    id: idField
                    objectName: "channel_id"
                    visible: pane.info.mine ?? false
                    Layout.maximumWidth: 200
                    Layout.preferredWidth: 200
                    problem: pane.channels.idProblem !== ""
                    text: pane.info.name ?? ""
                    onEditingFinished: pane.channels.rename(text)
                    ToolTip.visible: hovered
                    ToolTip.text: pane.channels.idProblem !== "" ? pane.channels.idProblem : "The id: it names the channel in slots, conditions and Home Assistant"
                    Binding { target: idField; property: "text"; value: pane.info.name ?? ""; when: !idField.activeFocus; restoreMode: Binding.RestoreNone }
                }
                Item { Layout.fillWidth: true }
            }

            SlotFadeText {
                objectName: "channel_about"
                width: parent.width
                markup: pane.channels.tools.help(pane.info.about ?? "", Theme.mode, pane.info.link ?? "", "")
            }

            UsedBy {
                objectName: "channel_used_by"
                tools: pane.channels.tools
                where: pane.info.where ?? []
                none: pane.info.none ?? ""
                width: parent.width
                onSlotPicked: slot => pane.slotPicked(slot)
            }

            ProblemText {
                objectName: "channel_problem"
                width: parent.width
                text: pane.shownForm ? pane.shownForm.rest.join("\n") : ""
            }

            Item {
                id: stack
                objectName: "channel_forms"
                width: parent.width
                height: shownHeight
                property real shownHeight: 0
                Behavior on shownHeight { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }

                Repeater {
                    model: pane.channels.formKeys
                    Loader {
                        id: holder
                        required property string modelData
                        readonly property bool current: modelData === pane.info.formKey
                        property bool visited: false
                        onCurrentChanged: if (current) { visited = true; stack.shownHeight = formHeight }
                        Component.onCompleted: if (current) visited = true
                        objectName: "form_" + modelData
                        width: stack.width
                        active: visited || pane.channels.prebuilt.indexOf(modelData) >= 0
                        opacity: current ? 1 : 0
                        visible: opacity > 0
                        Behavior on opacity { NumberAnimation { duration: Theme.fade; easing.type: Easing.InOutQuad } }
                        // the height of the stack follows the form shown
                        readonly property real formHeight: item ? item.height : 0
                        onFormHeightChanged: if (current) stack.shownHeight = formHeight
                        sourceComponent: FormView {
                            width: holder.width
                            form: pane.channels.formOf(holder.modelData)
                            preview: previews
                        }
                    }
                }
            }
        }
    }

    Component {
        id: previews
        Item {
            id: slot
            property string part
            property string strip
            property var values: ({})
            implicitWidth: drawing.item ? drawing.item.implicitWidth : 0
            implicitHeight: drawing.item ? drawing.item.implicitHeight : 0
            // the part is told after the item is made
            Loader {
                id: drawing
                active: slot.part !== ""
                sourceComponent: PartPreview { model: pane.channels.partModel(slot.part) }
            }
        }
    }
}
