// The form of a `Form` (see `forms/form.py`): a row per option under the headings of its groups, with a line between
// rows. A row that comes and goes (an option shown with another one) grows in and out; a new value changes the row in
// place. Beside the options of a group about a part of the strip goes a preview of what they do (`preview`, a stand-in
// until the drawing of the device has one). Everything is given by the form; there is no code per option.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Column {
    id: view
    required property QtObject form
    // the column of names; pages that show several forms give the widest one so their fields line up
    property real titleWidth: form.titleWidth
    property Component preview: PartPreviewPlaceholder {}
    signal revealed(Item item)

    spacing: 0
    onVisibleChanged: form.active = visible
    Component.onCompleted: form.active = visible

    function item(name) {
        for (let i = 0; i < rows.count; i++) {
            const found = rows.itemAt(i)
            if (found && found.key === name) return found
        }
        return null
    }

    // Shows the row of an option and gives its field the focus.
    function reveal(name) {
        const found = item(name)
        if (!found) return
        found.focusField()
        revealed(found)
    }

    Connections {
        target: view.form
        function onRevealRequested(name) { view.reveal(name) }
    }

    Repeater {
        id: rows
        model: view.form.rows

        Column {
            id: line
            required property string key
            required property var spec
            required property var info
            objectName: "row_" + key
            width: view.width
            spacing: 0

            function focusField() { option.focusField() }

            Reveal {
                width: parent.width
                shown: line.info.visible !== false
                Column {
                    width: parent.width
                    Item {
                        width: parent.width
                        height: line.spec.groupStart && line.spec.group !== "" ? heading.height + Theme.space.s : 0
                        visible: height > 0
                        Row {
                            id: heading
                            width: parent.width
                            spacing: Theme.space.m
                            Label {
                                text: line.spec.group.toUpperCase()
                                font.pointSize: Theme.fontSize.caption
                                font.bold: true
                                font.letterSpacing: 1
                                color: Theme.colors.text_muted
                                topPadding: Theme.space.m
                                width: line.spec.preview !== "" ? implicitWidth : parent.width
                            }
                            Loader {
                                visible: line.spec.preview !== ""
                                sourceComponent: line.spec.preview !== "" ? view.preview : null
                                onLoaded: {
                                    item.part = Qt.binding(() => line.spec.preview)
                                    item.strip = Qt.binding(() => view.form.stripType)
                                    item.values = Qt.binding(() => view.form.resolved)
                                }
                            }
                        }
                    }
                    Divider { width: parent.width; visible: line.spec.divided === true }
                    OptionRow {
                        id: option
                        width: parent.width
                        form: view.form
                        spec: line.spec
                        info: line.info
                        titleWidth: view.titleWidth
                        suggestKey: line.spec.suggests || line.spec.suggestColumns.length > 0 ? line.spec.name : ""
                        start: null
                        onValueEdited: value => view.form.setValue(line.key, value)
                        onResetRequested: view.form.reset(line.key)
                    }
                }
            }
        }
    }
}
