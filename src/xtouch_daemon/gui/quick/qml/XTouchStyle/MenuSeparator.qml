import QtQuick
import QtQuick.Templates as T
import XTouch

T.MenuSeparator {
    implicitHeight: Theme.space.s + 1
    contentItem: Rectangle { implicitHeight: 1; color: Theme.colors.border }
    verticalPadding: Theme.space.xs
}
