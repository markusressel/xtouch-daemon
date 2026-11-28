// The option rows of the parts an entry of the controls of a slot sets (Fader, Encoder, Select, Rec, Solo, Meter,
// Color, LCD line, and Id): the form of the entry (`controls.entryForm(index)`). A part removed with its reset
// button goes back to what the slot shows.
import QtQuick
import XTouch
import XTouch.Forms

FormView {
    required property QtObject controls
    property int entryIndex: 0
    objectName: "controls_parts"
    form: controls.entryForm(entryIndex)
}
