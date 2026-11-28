// One section on its page: heading, help, the problems of the whole section, and its card: the button to add the
// section while the file has none, else its connection or plugins and the form of its options.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls
import XTouch.Forms

Column {
    id: block
    required property QtObject app
    required property QtObject section
    property bool plugins: false
    readonly property QtObject form: section.form
    signal revealed(Item item)

    objectName: "section_" + section.name
    spacing: Theme.space.m

    function reveal(name) { view.reveal(name) }

    Item {
        width: parent.width
        height: Math.max(heading.height, remove.visible ? remove.height : 0)
        Row {
            id: heading
            spacing: Theme.space.m
            Label {
                objectName: "section_title_" + block.section.name
                text: block.section.title
                font.pointSize: Theme.fontSize.title
                font.bold: true
                color: Theme.colors.text
                anchors.verticalCenter: parent.verticalCenter
            }
            Label {
                text: "[" + block.section.name + "]"
                color: Theme.colors.text_muted
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Button {
            id: remove
            objectName: "remove_" + block.section.name
            visible: block.section.optional && block.section.present
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            icon.source: "image://icon/delete-outline"
            icon.color: Theme.colors.error
            text: "Remove [" + block.section.name + "]"
            onClicked: block.section.remove()
        }
    }

    HelpLabel {
        width: parent.width
        text: block.form.tools.help(block.section.help, Theme.mode, block.section.link, "")
    }

    Reveal {
        width: parent.width
        shown: block.form.rest.length > 0
        Banner {
            objectName: "problems_" + block.section.name
            width: parent.width
            tone: "bad"
            text: block.form.rest.join("\n")
        }
    }

    // the plugins of the voice chat clients: they show without the section too
    Repeater {
        model: block.plugins ? block.section.plugins : []
        PluginBox { required property QtObject modelData; width: block.width; box: modelData }
    }

    Reveal {
        width: parent.width
        shown: !block.section.present
        Card {
            width: parent.width
            Label {
                width: parent.width - 2 * Theme.space.m
                text: block.section.absent
                wrapMode: Text.Wrap
                color: Theme.colors.text
            }
            Button {
                objectName: "add_" + block.section.name
                highlighted: true
                icon.source: "image://icon/plus"
                text: "Add [" + block.section.name + "]"
                onClicked: block.section.add()
            }
        }
    }

    Reveal {
        width: parent.width
        shown: block.section.present
        Column {
            width: parent.width
            spacing: Theme.space.m
            Loader {
                width: parent.width
                active: block.section.live !== null
                sourceComponent: ConnectionBox { width: block.width; section: block.section }
            }
            Card {
                width: parent.width
                FormView {
                    id: view
                    width: parent.width
                    form: block.form
                    onRevealed: item => block.revealed(item)
                }
                Label {
                    visible: block.section.note !== ""
                    width: parent.width
                    text: block.section.note
                    color: Theme.colors.text_muted
                    font.pointSize: Theme.fontSize.caption
                }
            }
        }
    }
}
