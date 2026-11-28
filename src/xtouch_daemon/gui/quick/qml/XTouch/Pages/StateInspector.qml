// The right of the page States: the state or mode picked (its id, where it is used, what the daemon says about it, its
// override and its last day), and the form in the order of the questions: a state or a mode, on while its sources are
// on or while a condition holds (never both: switching asks first), and the delays. What comes and goes grows in and out.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch
import XTouch.Controls
import XTouch.Forms

SlotScroll {
    id: pane
    required property QtObject states
    readonly property var info: states.inspector
    readonly property var live: states.liveInfo
    readonly property bool present: !(info.empty ?? true)
    // one column of names for the whole form, also for the rows that are no option
    readonly property real names: Math.max(states.modeForm.titleWidth, states.sourcesForm.titleWidth, states.delaysForm.titleWidth, measure.width)
    signal slotPicked(int slot)

    objectName: "state_inspector"
    contentHeight: Math.max(height, content.height + Theme.space.s)

    TextMetrics { id: measure; text: "Condition  " }

    function renameId() {
        idField.forceActiveFocus()
        idField.selectAll()
    }

    // another state: what the inspector shows dips and comes back with the new one
    property string key: states.current
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
        width: pane.width - Theme.space.s - Theme.space.l
        height: column.height
        Behavior on height { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }

        Column {
            id: column
            width: parent.width
            spacing: Theme.space.m

            Reveal {
                width: parent.width
                shown: !pane.present
                SlotFadeText {
                    objectName: "states_empty"
                    width: parent.width
                    markup: pane.states.tools.help(pane.info.emptyText ?? "", Theme.mode, "", "")
                }
            }

            Reveal {
                width: parent.width
                shown: pane.present
                Column {
                    width: parent.width
                    spacing: Theme.space.m

                    RowLayout {
                        width: parent.width
                        spacing: Theme.space.m
                        FadeText {
                            objectName: "state_title"
                            text: pane.info.title ?? ""
                            font.pointSize: Theme.fontSize.section
                            font.bold: true
                            color: Theme.colors.text
                        }
                        TextField {
                            id: idField
                            objectName: "state_id"
                            Layout.preferredWidth: 200
                            Layout.maximumWidth: 200
                            problem: pane.states.idProblem !== ""
                            text: pane.info.name ?? ""
                            onEditingFinished: pane.states.rename(text)
                            ToolTip.visible: hovered
                            ToolTip.text: pane.states.idProblem !== "" ? pane.states.idProblem : "The id: it names the state in conditions, Home Assistant and `xtouch-daemon mode`"
                            Binding { target: idField; property: "text"; value: pane.info.name ?? ""; when: !idField.activeFocus; restoreMode: Binding.RestoreNone }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    UsedBy {
                        objectName: "state_used_by"
                        tools: pane.states.tools
                        where: pane.info.where ?? []
                        none: pane.info.none ?? ""
                        width: parent.width
                        onSlotPicked: slot => pane.slotPicked(slot)
                    }

                    RowLayout {
                        width: parent.width
                        spacing: Theme.space.s
                        SlotFadeText {
                            objectName: "state_live"
                            text: pane.live.text ?? ""
                            pointSize: Theme.fontSize.body
                            color: Theme.colors.text
                            Layout.fillWidth: true
                        }
                        Segmented {
                            objectName: "override"
                            items: pane.live.segments ?? []
                            onPicked: value => pane.states.override(value)
                        }
                    }

                    Reveal {
                        width: parent.width
                        shown: pane.live.hasHistory ?? false
                        HistoryBars {
                            objectName: "state_history"
                            tools: pane.states.tools
                            history: pane.live.history ?? []
                            width: parent.width
                        }
                    }

                    ProblemText {
                        objectName: "state_problem"
                        width: parent.width
                        text: pane.info.problem ?? ""
                    }

                    Card {
                        width: parent.width
                        objectName: "state_form"
                        spacing: Theme.space.xs

                        // State or mode
                        Row {
                            spacing: Theme.space.s
                            Label { width: pane.names; text: "Kind"; anchors.verticalCenter: parent.verticalCenter }
                            Segmented {
                                objectName: "kind"
                                items: pane.info.kind ?? []
                                onPicked: value => pane.states.setMode(value === "mode")
                            }
                        }
                        SlotFadeText {
                            x: pane.names + Theme.space.s
                            width: parent.width - x
                            text: pane.info.kindHelp ?? ""
                        }
                        FormView {
                            width: parent.width
                            form: pane.states.modeForm
                            titleWidth: pane.names
                        }
                        Divider { width: parent.width }

                        // sources or a condition
                        Row {
                            spacing: Theme.space.s
                            Label { width: pane.names; text: "On while"; anchors.verticalCenter: parent.verticalCenter }
                            Segmented {
                                id: onWhile
                                objectName: "on_while"
                                items: pane.info.onWhile ?? []
                                onPicked: value => pane.states.setComposed(value === "condition")
                            }
                        }
                        SlotFadeText {
                            x: pane.names + Theme.space.s
                            width: parent.width - x
                            text: pane.info.onWhileHelp ?? ""
                        }
                        Reveal {
                            width: parent.width
                            shown: !(pane.info.composed ?? false)
                            Column {
                                width: parent.width
                                spacing: Theme.space.xs
                                SlotFadeText {
                                    objectName: "sources_hint"
                                    width: parent.width
                                    text: pane.info.sourcesHint ?? ""
                                }
                                FormView {
                                    width: parent.width
                                    form: pane.states.sourcesForm
                                    titleWidth: pane.names
                                }
                                Reveal {
                                    width: parent.width
                                    shown: pane.info.canAddSource ?? false
                                    Button {
                                        id: addSource
                                        objectName: "add_source"
                                        text: "Add source"
                                        icon.source: "image://icon/plus"
                                        onClicked: sourceMenu.open()
                                    }
                                }
                            }
                        }
                        Reveal {
                            width: parent.width
                            shown: pane.info.composed ?? false
                            Column {
                                width: parent.width
                                spacing: Theme.space.xs
                                Row {
                                    width: parent.width
                                    spacing: Theme.space.s
                                    Label { width: pane.names; text: "Condition"; anchors.verticalCenter: parent.verticalCenter }
                                    ConditionField {
                                        id: whenField
                                        objectName: "when_field"
                                        width: parent.width - pane.names - Theme.space.s
                                        present: false
                                        placeholder: "e.g. call and not gaming"
                                        text: pane.info.when ?? ""
                                        states: pane.info.whenStates ?? []
                                        onCommitted: text => pane.states.setWhen(text)
                                    }
                                }
                                ProblemText {
                                    objectName: "when_error"
                                    x: pane.names + Theme.space.s
                                    width: parent.width - x
                                    text: pane.info.whenError ?? ""
                                }
                                HelpLabel {
                                    x: pane.names + Theme.space.s
                                    width: parent.width - x
                                    text: pane.states.tools.help(pane.info.whenHelp ?? "", Theme.mode, pane.states.conditionLink, "")
                                }
                            }
                        }
                        Divider { width: parent.width }

                        // delays and the override
                        ToolButton {
                            objectName: "delays_toggle"
                            text: "Delays and overrides"
                            icon.source: "image://icon/" + (pane.info.delaysOpen ? "chevron-down" : "chevron-right")
                            display: AbstractButton.TextBesideIcon
                            onClicked: pane.states.setDelaysOpen(!pane.info.delaysOpen)
                        }
                        FormView {
                            width: parent.width
                            form: pane.states.delaysForm
                            titleWidth: pane.names
                        }
                    }
                }
            }
        }
    }

    ActionMenu {
        id: sourceMenu
        objectName: "source_menu"
        anchor: addSource
        onAboutToShow: sections = pane.states.sourceEntries()
        onTriggered: action => pane.states.addSource(action)
    }

    // switching between sources and a condition removes what the other had: asked first
    Popover {
        id: question
        objectName: "switch_question"
        anchor: onWhile
        title: pane.states.switchQuestion.title ?? ""
        onClosed: pane.states.cancelSwitch()
        Label {
            objectName: "switch_text"
            Layout.fillWidth: true
            text: pane.states.switchQuestion.text ?? ""
            textFormat: Text.RichText
            wrapMode: Text.Wrap
        }
        RowLayout {
            spacing: Theme.space.s
            Button {
                objectName: "switch_confirm"
                text: pane.states.switchQuestion.accept ?? "Remove and switch"
                highlighted: true
                onClicked: pane.states.confirmSwitch()
            }
            Button {
                objectName: "switch_cancel"
                text: "Cancel"
                onClicked: question.close()
            }
        }
    }
    Connections {
        target: pane.states
        function onQuestionChanged() {
            if (pane.states.switchQuestion.title !== undefined) question.open()
            else question.close()
        }
        function onWhenRequested() { whenField.editor.forceActiveFocus() }
    }
}
