// The log of the daemon (window/log.py): the records of a level and above, a search that marks its matches, and Follow
// that keeps the latest records in view. The text is the document of the area, which the backend fills.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import XTouch

Rectangle {
    id: panel
    required property QtObject app
    readonly property QtObject log: app.shell.logView
    /// the least height that shows the bar and a line of the log
    readonly property real leastHeight: column.implicitHeight - flick.implicitHeight + Theme.space.s + fontMetrics.lineSpacing

    objectName: "logPanel"
    color: Theme.colors.sunken
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    FontMetrics { id: fontMetrics; font: area.font }

    ColumnLayout {
        id: column
        anchors { fill: parent; margins: Theme.space.s; leftMargin: Theme.space.l; rightMargin: Theme.space.l }
        spacing: Theme.space.s

        RowLayout {
            spacing: Theme.space.s
            Label { text: "Level" }
            ComboBox {
                objectName: "log_level"
                model: panel.log.levels
                currentIndex: panel.log.levelIndex
                onActivated: index => panel.log.setLevelIndex(index)
                property string tip: "The records of this level and above"
            }
            TextField {
                id: search
                objectName: "log_search"
                Layout.fillWidth: true
                placeholderText: "Search"
                text: panel.log.search
                onTextEdited: panel.log.setSearch(text)
                onAccepted: panel.log.nextMatch(area.selectionEnd)
                property string tip: "Marks the text in the log, ignoring case. Enter goes to the next match."
            }
            Label {
                objectName: "log_matches"
                text: panel.log.matchesText
                color: Theme.colors.text_muted
                font.pointSize: Theme.fontSize.caption
            }
            Button {
                objectName: "log_follow"
                text: "Follow"
                checkable: true
                checked: panel.log.follow
                onClicked: panel.log.setFollow(checked)
                property string tip: "Keeps the latest records in view. Scrolling up stops it, scrolling to the end starts it."
            }
        }

        // why the log can't come from the daemon now
        Label {
            objectName: "log_message"
            visible: text !== ""
            text: panel.log.message
            color: Theme.colors.text_muted
            font.pointSize: Theme.fontSize.caption
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }

        Flickable {
            id: flick
            property bool scrolling: false
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: fontMetrics.lineSpacing
            implicitHeight: fontMetrics.lineSpacing
            clip: true
            contentWidth: width
            contentHeight: area.height
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            function toEnd() {
                scrolling = true
                contentY = Math.max(0, contentHeight - height)
                scrolling = false
            }
            onContentHeightChanged: if (panel.log.follow) Qt.callLater(toEnd)
            onContentYChanged: if (!scrolling) panel.log.scrolled(contentY >= contentHeight - height - 1)

            TextArea {
                id: area
                objectName: "log_text"
                width: flick.width
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.RichText
                font.family: "monospace"
                font.pointSize: Theme.fontSize.caption
                background: null
                padding: 0
                Component.onCompleted: panel.log.attach(area.textDocument)
            }
        }
    }

    Connections {
        target: panel.log
        function onScrollToEnd() { Qt.callLater(flick.toEnd) }
        function onSelectRange(start, end) {
            area.select(start, end)
            const at = area.positionToRectangle(start)
            if (at.y < flick.contentY || at.y + at.height > flick.contentY + flick.height)
                flick.contentY = Math.max(0, Math.min(at.y, flick.contentHeight - flick.height))
        }
    }
}
