// What is wrong with an option, in the error color: it fades in and grows in as a problem comes, and out as it goes.
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Controls

Reveal {
    id: problem
    property string text
    shown: text !== ""
    // the text stays while the line fades out
    property string kept
    onTextChanged: if (text !== "") kept = text

    Label {
        width: parent.width
        text: problem.kept
        wrapMode: Text.Wrap
        color: Theme.colors.error
        font.pointSize: Theme.fontSize.caption
    }
}
