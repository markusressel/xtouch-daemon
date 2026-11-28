// The design tokens (see gui/quick/theme.py): the colors of the theme shown, the spacing scale, the radii, the sizes,
// and the durations of the motion (0 while it is off: in tests and screenshots).
pragma Singleton
import QtQuick

QtObject {
    readonly property QtObject backend: xtouchTheme

    readonly property string mode: backend.mode
    readonly property bool dark: backend.dark
    readonly property var colors: backend.colors
    readonly property var hardware: backend.hardware
    readonly property var lcd: backend.lcd
    readonly property real tintAlpha: backend.tintAlpha
    readonly property var space: backend.space
    readonly property var radius: backend.radius
    readonly property int controlHeight: backend.controlHeight
    readonly property var fontSize: backend.fontSize
    readonly property bool motion: backend.motion
    readonly property int fade: backend.fade
    readonly property int resize: backend.resize

    // `color` at `alpha` (0..1): the background a color tints
    function tint(color, alpha) {
        const c = Qt.color(color)
        return Qt.rgba(c.r, c.g, c.b, alpha)
    }
}
