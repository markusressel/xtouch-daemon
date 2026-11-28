// Help from the models as rich text (see `FormContext.help`): code, the words of the configuration in their colors,
// the DEFAULT chip and the link to the documentation, which opens in the browser.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Label {
    wrapMode: Text.Wrap
    textFormat: Text.RichText
    color: Theme.colors.text_muted
    linkColor: Theme.colors.accent
    font.pointSize: Theme.fontSize.caption
    onLinkActivated: link => Qt.openUrlExternally(link)
    HoverHandler { cursorShape: parent.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
}
