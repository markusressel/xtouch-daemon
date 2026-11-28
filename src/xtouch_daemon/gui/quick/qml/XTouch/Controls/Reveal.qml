// Something that comes and goes in a column: it grows from no height to its own and fades in, or shrinks away and
// fades out, so what is under it moves along (the QML side of `reveal`). Its child goes into it as the content.
import QtQuick
import XTouch

Item {
    id: reveal
    property bool shown: true
    default property alias content: holder.data

    implicitWidth: holder.childrenRect.width
    implicitHeight: shown ? holder.childrenRect.height : 0
    height: implicitHeight
    visible: height > 0 || shown
    clip: true
    opacity: shown ? 1 : 0
    Behavior on implicitHeight { NumberAnimation { duration: Theme.resize; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: Theme.resize } }

    Item {
        id: holder
        width: reveal.width
        height: childrenRect.height
    }
}
