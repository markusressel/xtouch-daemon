// A column of things that scrolls with the wheel at the speed of the desktop (the lines the system asks for, of
// `lineHeight` each) and glides to where it goes. It never moves by dragging: the things in it can be dragged.
import QtQuick
import QtQuick.Controls
import XTouch

Flickable {
    id: scroll
    property real lineHeight: 20
    readonly property real notch: Qt.styleHints.wheelScrollLines * lineHeight
    readonly property real maxY: Math.max(0, contentHeight - height)
    // where the scroll is going: while it glides, the next step adds to it
    readonly property real goal: glide.running ? glide.to : contentY

    interactive: false
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    contentWidth: width
    ScrollBar.vertical: ScrollBar { }

    function scrollTo(y) {
        const to = Math.max(0, Math.min(maxY, y))
        if (to === goal)
            return
        glide.stop()
        glide.from = contentY
        glide.to = to
        glide.start()
    }

    // `item` (of the content) in view, with `margin` around it
    function reveal(item, margin) {
        const top = item.mapToItem(contentItem, 0, 0).y - margin
        const bottom = top + item.height + 2 * margin
        if (top < goal)
            scrollTo(top)
        else if (bottom > goal + height)
            scrollTo(bottom - height)
    }

    NumberAnimation {
        id: glide
        target: scroll
        property: "contentY"
        duration: Theme.resize
        easing.type: Easing.OutCubic
    }

    WheelHandler {
        objectName: "wheel"
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: event => {
            const delta = event.pixelDelta.y !== 0 ? event.pixelDelta.y : event.angleDelta.y / 120 * scroll.notch
            scroll.scrollTo(scroll.goal - delta)
        }
    }
}
