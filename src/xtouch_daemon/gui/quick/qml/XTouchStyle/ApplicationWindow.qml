// The window: the colors of the theme for everything, also the controls of Qt's Basic style we keep.
import QtQuick
import QtQuick.Templates as T
import XTouch

T.ApplicationWindow {
    id: window
    color: Theme.colors.surface
    Behavior on color { ColorAnimation { duration: Theme.fade } }
    font.pointSize: Theme.fontSize.body

    palette {
        window: Theme.colors.surface
        windowText: Theme.colors.text
        base: Theme.colors.sunken
        alternateBase: Theme.colors.raised
        text: Theme.colors.text
        button: Theme.colors.raised
        buttonText: Theme.colors.text
        brightText: Theme.colors.on_accent
        highlight: Theme.colors.accent
        highlightedText: Theme.colors.on_accent
        link: Theme.colors.accent
        placeholderText: Theme.colors.placeholder
        toolTipBase: Theme.colors.raised
        toolTipText: Theme.colors.text
        mid: Theme.colors.border
        dark: Theme.colors.control_border
        light: Theme.tint(Theme.colors.text, 0.07)
        midlight: Theme.tint(Theme.colors.text, 0.12)
    }
}
