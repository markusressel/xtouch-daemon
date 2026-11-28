// The bar over the drawing: Select and Play and what they do, over the middle of the drawing the mode the device
// shows, and on the right whether the drawing is live, the hosted virtual device, and the test of the device. The
// middle stays over the middle of the drawing; where the ends need its place it moves aside as little as it can, and
// the hint at the left is cut rather than make the window wider.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Item {
    id: bar
    required property QtObject device
    readonly property QtObject backend: device
    property alias liveAnchor: livePill
    property alias modeAnchor: modePill
    property alias virtualAnchor: virtualPill

    implicitHeight: Theme.controlHeight
    objectName: "deviceBar"

    EntriesPopover { id: livePopover; objectName: "livePopover"; device: bar.device; kind: "live"; anchor: livePill }
    EntriesPopover { id: modesPopover; objectName: "modesPopover"; device: bar.device; kind: "modes"; anchor: modePill }
    EntriesPopover { id: virtualPopover; objectName: "virtualPopover"; device: bar.device; kind: "virtual"; anchor: virtualPill }

    // the segments of Select and Play keep the keys for the strips: no focus
    Row {
        id: segments
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: 0
        Button {
            id: select
            objectName: "modeSelect"
            text: "Select"
            icon.source: "image://icon/cursor-default-outline"
            flat: true
            checked: !bar.device.playing
            focusPolicy: Qt.NoFocus
            onClicked: bar.device.setPlaying(false)
            ToolTip.visible: hovered
            ToolTip.text: bar.device.selectTip
        }
        Button {
            id: play
            objectName: "modePlay"
            text: "Play"
            icon.source: "image://icon/hand-back-right-outline"
            flat: true
            checked: bar.device.playing
            enabled: bar.device.playEnabled
            focusPolicy: Qt.NoFocus
            onClicked: bar.device.setPlaying(true)
            HoverHandler { id: playHover }
            ToolTip.visible: playHover.hovered
            ToolTip.text: bar.device.playTip
        }
    }

    Label {
        id: hint
        objectName: "modeHint"
        anchors.left: segments.right
        anchors.leftMargin: Theme.space.s
        anchors.verticalCenter: parent.verticalCenter
        readonly property real stop: handPill.visible ? handPill.x - Theme.space.xs : limit
        readonly property real limit: (modePill.visible ? modePill.x : right.x) - Theme.space.s
        width: Math.max(0, Math.min(implicitWidth, limit - x - (handPill.visible ? handPill.width + Theme.space.xs : 0)))
        elide: Text.ElideRight
        text: bar.device.modeHint
        color: Theme.colors.text_muted
        font.pointSize: Theme.fontSize.caption
        HoverHandler { id: hintHover }
        ToolTip.visible: hintHover.hovered && bar.device.modeHintTip !== ""
        ToolTip.text: bar.device.modeHintTip
    }

    Pill {
        id: handPill
        objectName: "handPill"
        anchors.left: hint.right
        anchors.leftMargin: Theme.space.xs
        anchors.verticalCenter: parent.verticalCenter
        visible: bar.device.handStatus.text !== undefined
        text: visible ? bar.device.handStatus.text : ""
        tone: visible ? bar.device.handStatus.tone : "neutral"
        HoverHandler { id: handHover }
        ToolTip.visible: handHover.hovered && visible
        ToolTip.text: visible ? bar.device.handStatus.tip : ""
    }

    Pill {
        id: modePill
        objectName: "modePill"
        visible: bar.device.modeStatus.text !== undefined
        text: visible ? bar.device.modeStatus.text : ""
        tone: visible ? bar.device.modeStatus.tone : "neutral"
        clickable: true
        anchors.verticalCenter: parent.verticalCenter
        x: Math.max(Math.min((bar.width - width) / 2, right.x - Theme.space.s - width), segments.width + Theme.space.s)
        Behavior on x { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
        onClicked: modesPopover.open()
        HoverHandler { id: modeHover }
        ToolTip.visible: modeHover.hovered && visible
        ToolTip.text: visible ? bar.device.modeStatus.tip : ""
    }

    Row {
        id: right
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.space.xs
        Pill {
            id: livePill
            objectName: "livePill"
            anchors.verticalCenter: parent.verticalCenter
            text: bar.device.liveStatus.text !== undefined ? bar.device.liveStatus.text : ""
            tone: bar.device.liveStatus.tone !== undefined ? bar.device.liveStatus.tone : "neutral"
            clickable: true
            onClicked: livePopover.open()
            HoverHandler { id: liveHover }
            ToolTip.visible: liveHover.hovered && bar.device.liveStatus.tip !== undefined
            ToolTip.text: bar.device.liveStatus.tip !== undefined ? bar.device.liveStatus.tip : ""
        }
        Pill {
            id: virtualPill
            objectName: "virtualPill"
            anchors.verticalCenter: parent.verticalCenter
            visible: bar.device.virtualStatus.text !== undefined
            text: visible ? bar.device.virtualStatus.text : ""
            tone: visible ? bar.device.virtualStatus.tone : "neutral"
            clickable: true
            onClicked: virtualPopover.open()
        }
        Item { width: Theme.space.xs; height: 1 }
        Button {
            objectName: "testButton"
            text: "Test the device"
            icon.source: "image://icon/test-tube"
            checked: bar.device.testRunning
            visible: bar.device.testVisible
            enabled: bar.device.testEnabled
            focusPolicy: Qt.NoFocus
            onClicked: bar.device.toggleTest(!bar.device.testRunning)
            HoverHandler { id: testHover }
            ToolTip.visible: testHover.hovered
            ToolTip.text: bar.device.testTip
        }
        Button {
            objectName: "tryButton"
            text: "Try without a device"
            icon.source: "image://icon/play-circle-outline"
            visible: bar.device.tryVisible
            onClicked: bar.device.tryWithoutDevice()
            ToolTip.visible: hovered
            ToolTip.text: bar.device.tryTip
        }
        Button {
            objectName: "useVirtualButton"
            text: "Use the virtual device"
            icon.source: "image://icon/monitor-shimmer"
            visible: bar.device.useVirtualVisible
            onClicked: bar.device.useVirtualDevice()
            ToolTip.visible: hovered
            ToolTip.text: bar.device.useVirtualTip
        }
    }
}
