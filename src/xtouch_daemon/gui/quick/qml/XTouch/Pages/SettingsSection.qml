// The page of a section of the configuration: its title and help, what is wrong with it as a whole, and either a card with
// a button to add it (while the file has no such section) or the card with the form of its options. `second` is a
// section shown below it (the API under the MQTT broker); `plugins` shows the plugin of each voice chat client above.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls
import XTouch.Forms

Flickable {
    id: pane
    required property QtObject app
    required property QtObject section
    property QtObject second: null
    property bool plugins: false
    readonly property QtObject tools: section.form.tools

    contentWidth: width
    contentHeight: body.height + 2 * Theme.space.xl
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar {}

    function ensureVisible(item) {
        const y = item.mapToItem(contentItem, 0, 0).y
        if (y < contentY) contentY = y - Theme.space.m
        else if (y + item.height > contentY + height) contentY = y + item.height - height + Theme.space.m
    }

    Column {
        id: body
        x: Theme.space.xl
        y: Theme.space.xl
        width: Math.min(pane.width - 2 * Theme.space.xl, 900)
        spacing: Theme.space.l

        SectionBlock { width: parent.width; app: pane.app; section: pane.section; plugins: pane.plugins; onRevealed: item => pane.ensureVisible(item) }
        Loader {
            width: parent.width
            active: pane.second !== null
            sourceComponent: SectionBlock { width: body.width; app: pane.app; section: pane.second; onRevealed: item => pane.ensureVisible(item) }
        }
    }
}
