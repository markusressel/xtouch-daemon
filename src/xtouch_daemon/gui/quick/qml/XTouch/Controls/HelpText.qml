// The help under a field or on a card: muted, wrapped, with links that open in the browser (`learn more`).
import QtQuick
import QtQuick.Controls
import XTouch

Label {
    wrapMode: Text.Wrap
    textFormat: Text.StyledText
    color: Theme.colors.text_muted
    linkColor: Theme.colors.accent
    font.pointSize: Theme.fontSize.caption
    onLinkActivated: link => Qt.openUrlExternally(link)
    HoverHandler { cursorShape: parent.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
}
