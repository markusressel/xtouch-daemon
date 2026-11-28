// A number: typed or stepped (the buttons, Up and Down; the wheel only while it has the focus). Without a default of its
// own, it is empty while unset (its placeholder says what applies); stepping up from there starts where `row.start`
// says (e.g. the `min` of a binding) rather than a tiny step.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: field
    required property Item row
    readonly property var spec: row.spec
    readonly property bool integer: spec.kind === "integer"
    readonly property bool signed: spec.signed === true
    readonly property int decimals: integer ? 0 : signed ? 3 : 1
    readonly property real low: integer ? (spec.minimum ?? 0) : signed ? (spec.minimum ?? -1000000) : (spec.minimum ?? 0)
    readonly property real high: spec.maximum || 1000000
    readonly property bool unsettable: spec.default === null || spec.default === undefined
    readonly property var number: typeof row.shown === "number" ? row.shown : null
    readonly property real step: integer ? 1 : signed ? adaptive(number ?? 1) : 0.5
    readonly property alias input: edit

    implicitHeight: Theme.controlHeight
    implicitWidth: 140

    function adaptive(value) {
        const size = Math.abs(value)
        return size <= 0 ? 0.1 : Math.max(0.001, Math.pow(10, Math.floor(Math.log(size) / Math.LN10) - 1))
    }

    function format(value) {
        if (value === null || value === undefined) return ""
        if (integer) return String(Math.round(value))
        let text = value.toFixed(decimals)
        if (signed) text = text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, ".0")
        return text
    }

    function clamp(value) {
        return Math.max(low, Math.min(high, value))
    }

    function commit(value) {
        row.edit(value === null ? null : integer ? Math.round(value) : value)
    }

    function stepBy(direction) {
        let value = number
        if (value === null) {
            // a step up from "not set" starts where the option starts
            if (direction < 0) return
            const start = row.start()
            value = start !== null && start !== undefined ? start : low
            commit(clamp(value))
            return
        }
        const next = Math.round((value + direction * step) * 1000) / 1000
        commit(clamp(next))
    }

    TextField {
        id: edit
        objectName: "field_" + field.spec.name
        anchors { left: parent.left; right: stepper.left; rightMargin: Theme.space.xs; verticalCenter: parent.verticalCenter }
        placeholderText: field.row.placeholder
        problem: field.row.problem
        validator: DoubleValidator {
            bottom: field.low
            top: field.high
            decimals: field.decimals
            notation: DoubleValidator.StandardNotation
            locale: "C"
        }
        inputMethodHints: Qt.ImhFormattedNumbersOnly
        rightPadding: suffix.visible ? suffix.width + Theme.space.s : Theme.space.s
        onTextEdited: {
            if (text === "") {
                // with a default, an empty field waits: it goes back to the default when it loses the focus
                if (field.unsettable) field.commit(null)
            } else if (acceptableInput) {
                field.commit(Number(text))
            }
        }
        onEditingFinished: {
            if (text === "" && !field.unsettable) field.commit(null)
            else if (text !== "" && acceptableInput) text = field.format(field.clamp(Number(text)))
            else if (text !== "") text = field.format(field.number)
        }
        Keys.onUpPressed: field.stepBy(1)
        Keys.onDownPressed: field.stepBy(-1)
        Label {
            id: suffix
            visible: field.spec.percent === true && edit.text !== ""
            anchors { right: parent.right; rightMargin: Theme.space.s; verticalCenter: parent.verticalCenter }
            text: "%"
            color: Theme.colors.text_muted
        }
        WheelHandler {
            enabled: edit.activeFocus
            onWheel: event => field.stepBy(event.angleDelta.y > 0 ? 1 : -1)
        }
    }

    // while it is typed in, the number is the one typed: the text stays as it is (e.g. "1." on its way to "1.5"); a
    // change from elsewhere (undo) still shows
    Binding {
        target: edit
        property: "text"
        value: field.format(field.number)
        restoreMode: Binding.RestoreNone
        when: !edit.activeFocus
    }
    onNumberChanged: {
        if (edit.activeFocus && (edit.text === "" ? number !== null : Number(edit.text) !== number)) edit.text = format(number)
    }

    Row {
        id: stepper
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        IconButton { name: "minus"; tip: "Less"; focusPolicy: Qt.NoFocus; onClicked: field.stepBy(-1) }
        IconButton { name: "plus"; tip: "More"; focusPolicy: Qt.NoFocus; onClicked: field.stepBy(1) }
    }
}
