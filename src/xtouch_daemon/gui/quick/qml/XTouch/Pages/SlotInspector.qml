// The inspector: the slot picked and its candidate picked, or the overview of all slots while nothing is picked. The
// two cross-fade, and so does what the inspector shows when another candidate is picked; parts that come and go grow
// in and out.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls

SlotScroll {
    id: pane
    required property QtObject slots
    readonly property var info: slots.inspector
    readonly property bool inspecting: info.mode === "slot"
    readonly property real inset: Theme.space.l
    objectName: "inspector"
    contentHeight: Math.max(height, content.height + Theme.space.s)

    // both parts are there while they cross-fade
    Item {
        id: content
        x: Theme.space.s
        y: Theme.space.s
        width: pane.width - Theme.space.s - pane.inset
        height: pane.inspecting ? inspector.height : overview.height
        Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }

        SlotOverview {
            id: overview
            slots: pane.slots
            width: parent.width
            opacity: pane.inspecting ? 0 : 1
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Theme.resize } }
        }

        Rectangle {
            id: inspector
            objectName: "inspector_card"
            width: parent.width
            height: column.implicitHeight + 2 * Theme.space.m
            radius: Theme.radius.large
            color: Theme.colors.raised
            border.color: Theme.colors.border
            opacity: pane.inspecting ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Theme.resize } }

            // another candidate: what the inspector shows dips and comes back with the new candidate
            property int candidate: pane.slots.candidate
            property int slot: pane.slots.slot
            onCandidateChanged: dip.restart()
            onSlotChanged: dip.restart()
            SequentialAnimation {
                id: dip
                NumberAnimation { target: column; property: "opacity"; to: 0.35; duration: Theme.fade * 0.4 }
                NumberAnimation { target: column; property: "opacity"; to: 1; duration: Theme.fade }
            }

            Column {
                id: column
                x: Theme.space.m
                y: Theme.space.m
                width: parent.width - 2 * Theme.space.m
                spacing: Theme.space.s

                // Slot N › 1 games › 2 apps › dark
                Flow {
                    width: parent.width
                    spacing: Theme.space.xs
                    Text {
                        id: title
                        objectName: "inspector_title"
                        anchors.verticalCenter: undefined
                        height: Theme.controlHeight
                        verticalAlignment: Text.AlignVCenter
                        text: pane.info.title || ""
                        color: Theme.colors.slot
                        font.bold: true
                        font.pointSize: Theme.fontSize.section
                    }
                    Repeater {
                        model: pane.slots.crumbs
                        Row {
                            id: crumbItem
                            required property var row
                            required property string key
                            spacing: Theme.space.xs
                            Text {
                                height: Theme.controlHeight
                                verticalAlignment: Text.AlignVCenter
                                text: "›"
                                color: Theme.colors.text_muted
                            }
                            SlotCrumb {
                                objectName: "crumb_" + crumbItem.key
                                text: crumbItem.row.text
                                mark: crumbItem.row.mark
                                checked: crumbItem.row.checked
                                ToolTip.visible: hovered
                                ToolTip.text: crumbItem.row.tip
                                onClicked: {
                                    pane.slots.pickCrumb(crumbItem.row.row)
                                    checked = Qt.binding(() => crumbItem.row.checked)
                                }
                            }
                        }
                    }
                }

                // why the slot shows what it shows, and where its candidate is now
                Rectangle {
                    id: status
                    objectName: "status_box"
                    width: parent.width
                    height: statusColumn.implicitHeight + 2 * Theme.space.s
                    visible: pane.info.whyLive === true || (pane.info.channel || "") !== "" || (pane.info.hint || "") !== ""
                    radius: Theme.radius.small
                    color: Theme.tint(pane.info.whyTone === "good" ? Theme.colors.tone_good : Theme.colors.tone_neutral, 0.12)
                    Behavior on color { ColorAnimation { duration: Theme.fade } }
                    Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
                    Rectangle {
                        width: 3
                        height: parent.height
                        radius: 1
                        color: pane.info.whyTone === "good" ? Theme.colors.tone_good : Theme.colors.tone_neutral
                        Behavior on color { ColorAnimation { duration: Theme.fade } }
                    }

                    Column {
                        id: statusColumn
                        x: Theme.space.m
                        y: Theme.space.s
                        width: parent.width - Theme.space.m - Theme.space.s
                        spacing: Theme.space.xs

                        Reveal {
                            width: parent.width
                            shown: pane.info.whyLive === true
                            Column {
                                width: parent.width
                                spacing: Theme.space.xs
                                FadeText {
                                    objectName: "why_heading"
                                    text: pane.info.whyHeading || ""
                                    color: Theme.colors.text_muted
                                }
                                SlotFadeText {
                                    objectName: "why_empty"
                                    width: parent.width
                                    text: pane.info.whyEmpty || ""
                                    visible: text !== ""
                                }
                                SlotList {
                                    objectName: "why_steps"
                                    width: parent.width
                                    spacing: Theme.space.xs
                                    model: pane.slots.whySteps
                                    delegate: RowLayout {
                                        id: step
                                        required property var row
                                        required property string key
                                        width: ListView.view.width
                                        spacing: Theme.space.s
                                        Text {
                                            Layout.alignment: Qt.AlignTop
                                            text: step.row.mark
                                            color: Theme.colors[step.row.color]
                                            font.bold: true
                                            font.pointSize: Theme.fontSize.body
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignTop
                                            text: step.row.subject
                                            color: step.row.final ? Theme.colors.text : Theme.colors.text_muted
                                            font.bold: step.row.final
                                            font.pointSize: Theme.fontSize.body
                                        }
                                        SlotFadeText {
                                            Layout.fillWidth: true
                                            Layout.alignment: Qt.AlignTop
                                            markup: step.row.reason
                                        }
                                    }
                                }
                            }
                        }
                        SlotFadeText {
                            objectName: "channel_text"
                            width: parent.width
                            markup: pane.info.hasCandidate ? (pane.info.channel || "") : ""
                            visible: markup !== ""
                        }
                        SlotFadeText {
                            objectName: "hint_text"
                            width: parent.width
                            markup: pane.info.hint || ""
                            visible: markup !== ""
                        }
                    }
                }

                // what the candidate shows, and when
                Reveal {
                    width: parent.width
                    shown: pane.info.hasCandidate === true
                    Column {
                        width: parent.width
                        spacing: Theme.space.xs
                        RowLayout {
                            width: parent.width
                            spacing: Theme.space.s
                            Label { text: "Shows"; Layout.preferredWidth: 48 }
                            ComboBox {
                                id: shows
                                objectName: "shows_field"
                                Layout.fillWidth: true
                                editable: true
                                model: pane.info.showChoices || []
                                textRole: "text"
                                ToolTip.visible: hovered
                                ToolTip.delay: 600
                                ToolTip.text: "A channel, a pool (`auto`) or `-` for nothing"
                                readonly property string current: pane.info.shows || ""
                                onCurrentChanged: sync()
                                onModelChanged: sync()
                                function sync() {
                                    editText = current
                                    currentIndex = find(current)
                                }
                                Component.onCompleted: sync()
                                delegate: ItemDelegate {
                                    id: choice
                                    required property var modelData
                                    required property int index
                                    width: ListView.view.width
                                    text: modelData.text
                                    enabled: !modelData.header
                                    font.bold: modelData.header
                                    highlighted: shows.highlightedIndex === index
                                }
                                onActivated: index => pane.slots.setShows(model[index].text)
                                onAccepted: pane.slots.setShows(editText)
                                Connections {
                                    target: pane.slots
                                    function onFocusShows() { shows.forceActiveFocus(); shows.contentItem.selectAll() }
                                }
                                onActiveFocusChanged: if (!activeFocus) pane.slots.setShows(editText)
                            }
                        }
                        SlotFadeText {
                            width: parent.width
                            markup: pane.info.showHelp || ""
                        }
                        RowLayout {
                            width: parent.width
                            spacing: Theme.space.s
                            Label { text: "When"; Layout.preferredWidth: 48 }
                            ConditionField {
                                objectName: "when_field"
                                Layout.fillWidth: true
                                text: pane.info.when || ""
                                states: pane.info.conditionStates || []
                                targets: pane.info.conditionTargets || []
                                onCommitted: text => pane.slots.setWhen(text)
                            }
                        }
                        SlotFadeText {
                            width: parent.width
                            markup: pane.info.whenHelp || ""
                        }
                    }
                }

                // problems that belong to no row of the form below
                Reveal {
                    width: parent.width
                    shown: (pane.info.problem || "") !== ""
                    Label {
                        objectName: "problem_text"
                        width: parent.width
                        text: pane.info.problem || ""
                        color: Theme.colors.error
                        wrapMode: Text.Wrap
                    }
                }

                // the place of the candidate: where its look comes from, and the options of it
                Reveal {
                    width: parent.width
                    shown: !!pane.info.place && pane.info.place.title !== undefined
                    Column {
                        width: parent.width
                        spacing: Theme.space.xs
                        SectionHeader {
                            objectName: "place_title"
                            text: pane.info.place && pane.info.place.title || ""
                            topPadding: Theme.space.m
                        }
                        RowLayout {
                            width: parent.width
                            spacing: Theme.space.s
                            SlotFadeText {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                markup: pane.info.place && pane.info.place.parts || ""
                            }
                            Button {
                                objectName: "edit_origin"
                                Layout.alignment: Qt.AlignTop
                                text: pane.info.place && pane.info.place.button || ""
                                icon.source: "image://icon/pencil-outline"
                                onClicked: pane.slots.editOrigin()
                            }
                        }
                        SlotPlaceForm {
                            width: parent.width
                            slots: pane.slots
                            visible: !!pane.info.place && pane.info.place.form === true
                            optionPath: pane.info.place && pane.info.place.path || []
                            strip: pane.info.place && pane.info.place.strip || ""
                            allowed: pane.info.place && pane.info.place.allowed || []
                            pick: pane.info.place ? pane.info.place.pick === true : true
                        }
                    }
                }

                SlotControlsView {
                    width: parent.width
                    controls: pane.slots.controls
                }
            }
        }
    }

    Connections {
        target: pane.slots
        function onScrollRequested() { pane.scrollTo(0) }
    }
}
