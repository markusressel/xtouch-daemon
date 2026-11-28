// The form of a `Form` (see `forms/form.py`): a row per option under the headings of its groups, with a line between
// rows. A row that comes and goes (an option shown with another one) grows in and out; a new value changes the row in
// place. Beside the options of a group about a part of the strip goes a preview of what they do (`preview`, by default
// a `FormPartPreview`): left of the options while the form is wide, above them while it is narrow. Everything is given
// by the form; there is no code per option.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Column {
    id: view
    required property QtObject form
    // the column of names; pages that show several forms give the widest one so their fields line up
    property real titleWidth: form.titleWidth
    // what a group with a `preview` shows beside its options; it gets `part` (`encoder`, `display`, ...)
    property Component preview: FormPartPreview { form: view.form }
    // the width of a preview: the options of a group make room for it while the form is wide enough
    readonly property real previewWidth: form.previewWidth
    readonly property bool wide: width >= previewWidth + Theme.space.l + 20 * Theme.controlHeight
    signal revealed(Item item)

    spacing: 0
    onVisibleChanged: form.active = visible
    Component.onCompleted: form.active = visible

    // a preview was made: it shows its part, and the options of its group make room for it
    function previewLoaded(item, part) {
        item.part = part
    }

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

    // How much taller than its options the preview of the group of row `index` is: the last row of the group makes
    // room for the rest (the preview stands beside the options, it takes no room of its own).
    function lacking(index) {
        let content = 0
        for (let i = index; i >= 0; i--) {
            const found = rows.itemAt(i)
            if (!found) return 0
            content += found.bodyHeight
            if (found.spec.groupStart) {
                const preview = found.previewHeight
                return Math.max(0, found.headingHeight + preview - content)
            }
        }
        return 0
    }

    Repeater {
        id: rows
        model: view.form.rows

        Item {
            id: line
            required property string key
            required property var spec
            required property var info
            required property int index
            // the preview stands beside the options (not above them) in this row
            readonly property bool beside: line.spec.preview !== "" && view.wide
            readonly property real bodyHeight: body.height
            readonly property real headingHeight: heading.height
            property real previewHeight: 0
            // the preview of a group stands out of its first row: that row is over the ones below
            z: line.spec.groupStart && line.beside ? 1 : 0
            objectName: "row_" + key
            width: view.width
            height: stack.height

            function focusField() { option.focusField() }

            // the preview of the group beside its options, under the heading: it stands over the rows of the group
            // (they are indented, and the last one makes room for what it is taller by)
            Loader {
                y: line.headingHeight
                active: line.spec.groupStart && line.beside
                sourceComponent: view.preview
                onLoaded: {
                    view.previewLoaded(item, line.spec.preview)
                    line.previewHeight = Qt.binding(() => item ? item.implicitHeight : 0)
                }
            }

            Column {
                id: stack
                width: parent.width
                spacing: 0

                Reveal {
                    width: parent.width
                    shown: line.info.visible !== false
                    Column {
                        id: body
                        width: parent.width
                        Item {
                            id: heading
                            width: parent.width
                            height: line.spec.groupStart && line.spec.group !== "" ? heading_text.height + Theme.space.s : 0
                            visible: height > 0
                            Label {
                                id: heading_text
                                text: line.spec.group.toUpperCase()
                                font.pointSize: Theme.fontSize.caption
                                font.bold: true
                                font.letterSpacing: 1
                                color: Theme.colors.text_muted
                                topPadding: Theme.space.m
                                width: parent.width
                            }
                        }
                        // the preview of the group: above its options, or beside them (then it takes no room here)
                        Item {
                            width: parent.width
                            height: line.spec.groupStart && line.spec.preview !== "" && !line.beside ? above.height + Theme.space.s : 0
                            visible: height > 0
                            Loader {
                                id: above
                                active: line.spec.groupStart && line.spec.preview !== "" && !line.beside
                                sourceComponent: view.preview
                                onLoaded: view.previewLoaded(item, line.spec.preview)
                            }
                        }
                        Divider {
                            x: line.beside ? view.previewWidth + Theme.space.l : 0
                            width: parent.width - x
                            visible: line.spec.divided === true
                        }
                        OptionRow {
                            id: option
                            x: line.beside ? view.previewWidth + Theme.space.l : 0
                            width: parent.width - x
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
                // the last row of a group with its preview beside it: room for what the preview is taller by
                Item {
                    width: parent.width
                    height: line.beside && line.spec.groupEnd === true ? view.lacking(line.index) : 0
                }
            }
        }
    }
}
