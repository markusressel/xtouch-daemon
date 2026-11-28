// One option of a form: its name, the field for its kind, its help and its problems. The name is left of the field in a
// column the rows of a form share, or above it where the row is too narrow for both. It is the same row for every
// option, and for the columns of a table or a binding inside a field: `spec` says what the option is (see
// `forms/model.py`), `info` what it shows now (`value`, `placeholder`, `problems`, ...); an edit is `valueEdited`.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: option

    required property QtObject form
    property var spec: ({})
    property var info: ({})
    property real titleWidth: 144
    property bool nested: false
    property string suggestKey: ""
    property var suggestLine: ({})
    property var start: null
    property string hint: ""
    property string helpHtml: form.tools.help(spec.help ?? "", Theme.mode, spec.link ?? "", info.helpDefault ?? spec.defaultText ?? "")
    signal valueEdited(var value)
    signal resetRequested()
    signal picked(string value, var extra)
    signal settings()

    readonly property string kind: spec.kind ?? "text"
    readonly property var value: info.value === undefined ? null : info.value
    readonly property var shown: {
        if (info.shown !== undefined) return info.shown
        const value = option.value
        return value === null ? (spec.default === undefined ? null : spec.default) : value
    }
    readonly property string placeholder: info.placeholder ?? ""
    readonly property string problems: info.problems ?? ""
    readonly property bool problem: problems !== ""
    readonly property bool tall: spec.tall ?? false
    // a margin both ways: the scroll bar that comes with a taller row must not switch it back
    property bool narrow: false
    readonly property real narrowBelow: titleWidth + Theme.space.s + 320
    readonly property real widest: 640
    onWidthChanged: {
        if (!narrow && width < narrowBelow) narrow = true
        else if (narrow && width > narrowBelow + Theme.space.m) narrow = false
    }
    Component.onCompleted: narrow = width < narrowBelow

    function edit(value) { valueEdited(value) }

    // the field takes the keyboard focus (a problem leads here)
    function focusField() {
        const loaded = loader.item
        const target = loaded ? (loaded.input ?? loaded.combo ?? loaded) : null
        if (target) target.forceActiveFocus()
    }

    implicitHeight: column.implicitHeight + 2 * Theme.space.xs
    height: implicitHeight

    Column {
        id: column
        y: Theme.space.xs
        width: option.width
        spacing: Theme.space.xs

        Item {
            id: top
            width: parent.width
            readonly property real fieldX: option.narrow ? 0 : option.titleWidth + Theme.space.s
            readonly property real fieldWidth: Math.max(0, Math.min(option.narrow ? width : option.widest, width - fieldX) - reset.width - Theme.space.xs)
            readonly property real titleHeight: title.visible ? title.implicitHeight : 0
            height: option.narrow
                ? titleHeight + (titleHeight > 0 ? Theme.space.xs : 0) + loader.height
                : Math.max(titleHeight, loader.height)

            Label {
                id: title
                objectName: "title_" + (option.spec.name ?? "")
                visible: (option.spec.titleText ?? "") !== ""
                x: 0
                y: option.tall || option.narrow ? 0 : (loader.height - implicitHeight) / 2
                width: option.narrow ? parent.width : option.titleWidth
                text: option.spec.titleText ?? ""
                wrapMode: Text.Wrap
                color: Theme.colors.text
                HoverHandler { id: titleHover }
                ToolTip.visible: titleHover.hovered && (option.spec.titleTip ?? "") !== ""
                ToolTip.text: option.spec.titleTip ?? ""
            }

            // the fields that hold rows of their own (tables, buttons, bindings) load by their file: a row inside a
            // row would be a cycle of types
            Loader {
                id: loader
                x: top.fieldX
                y: option.narrow && top.titleHeight > 0 ? top.titleHeight + Theme.space.xs : 0
                width: top.fieldWidth
                height: item ? item.implicitHeight : 0
                sourceComponent: {
                    switch (option.kind) {
                    case "text": case "secret": case "path": case "action": case "data": return names
                    case "integer": case "number": return numbers
                    case "switch": return switches
                    case "choice": return choices
                    case "color": return colors
                    case "list": return chips
                    case "numbers": return toggles
                    }
                    return null
                }
                Component.onCompleted: {
                    const lazy = { tables: "TablesField.qml", button: "ButtonField.qml", claim: "ButtonField.qml", binding: "BindingField.qml" }
                    if (lazy[option.kind] !== undefined) setSource(lazy[option.kind], { row: option })
                }
            }

            IconButton {
                id: reset
                objectName: "reset_" + (option.spec.name ?? "")
                x: loader.x + loader.width + Theme.space.xs
                y: option.tall || option.narrow ? loader.y : loader.y + Math.max(0, (loader.height - height) / 2)
                name: option.info.resetIcon ?? "restore"
                tip: option.info.resetTip ?? "Back to the default"
                opacity: option.info.resettable ? 1 : 0
                enabled: option.info.resettable === true
                visible: opacity > 0 || !option.nested
                Behavior on opacity { NumberAnimation { duration: Theme.fade } }
                onClicked: option.resetRequested()
            }
        }

        Item {
            id: details
            width: parent.width
            height: stack.height
            Column {
                id: stack
                x: option.narrow ? 0 : option.titleWidth + Theme.space.s
                width: Math.min(parent.width - x, option.narrow ? parent.width : option.widest + 2 * Theme.space.s + reset.width)
                spacing: 2

                Reveal {
                    width: parent.width
                    shown: (option.info.meaning ?? "") !== ""
                    HelpLabel {
                        objectName: "meaning_" + (option.spec.name ?? "")
                        width: parent.width
                        text: option.form.tools.help(option.info.meaning ?? "", Theme.mode, "", "")
                    }
                }
                Reveal {
                    width: parent.width
                    shown: option.info.matches !== undefined && option.info.matches !== null
                    Label {
                        objectName: "matches_" + (option.spec.name ?? "")
                        width: parent.width
                        text: option.info.matches ? option.info.matches.text : ""
                        wrapMode: Text.Wrap
                        font.pointSize: Theme.fontSize.caption
                        color: option.info.matches && !option.info.matches.found ? Theme.colors.warning : Theme.colors.text_muted
                        Behavior on color { ColorAnimation { duration: Theme.fade } }
                    }
                }
                Reveal {
                    width: parent.width
                    shown: option.hint !== ""
                    Row {
                        width: parent.width
                        spacing: Theme.space.s
                        HelpLabel {
                            width: parent.width - settingsButton.width - parent.spacing
                            text: option.form.tools.help(option.hint, Theme.mode, "", "")
                        }
                        Button {
                            id: settingsButton
                            flat: true
                            text: "Settings"
                            onClicked: option.settings()
                        }
                    }
                }
                Reveal {
                    width: parent.width
                    shown: option.helpHtml !== ""
                    HelpLabel {
                        objectName: "help_" + (option.spec.name ?? "")
                        width: parent.width
                        text: option.helpHtml
                    }
                }
                Reveal {
                    width: parent.width
                    shown: option.kind === "secret"
                    HelpLabel { width: parent.width; text: "It is saved as plain text in the configuration file." }
                }
                ProblemText {
                    objectName: "problem_" + (option.spec.name ?? "")
                    width: parent.width
                    text: option.problems
                }
            }
        }
    }

    // -- the fields of the kinds ------------------------------------------------------------------------------------

    Component { id: names; NameField { row: option } }
    Component { id: numbers; NumberField { row: option } }
    Component {
        id: switches
        Item {
            implicitHeight: toggle.implicitHeight
            Switch {
                id: toggle
                objectName: "switch_" + option.spec.name
                onToggled: option.edit(checked)
            }
            Binding { target: toggle; property: "checked"; value: option.shown === true; restoreMode: Binding.RestoreNone }
        }
    }
    Component {
        id: choices
        ChoiceField { row: option; onChosen: value => option.edit(value) }
    }
    Component {
        id: colors
        ColorField { row: option; onChosen: value => option.edit(value) }
    }
    Component { id: chips; ChipsField { row: option } }
    Component { id: toggles; NumbersField { row: option } }
}
