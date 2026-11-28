// The preview of a part of the strip (`PartPreview` of `XTouch.Device`) beside the options of its group in a form: it
// plays what the values of the form do on that part. `FormView` makes one per group with a `preview` and gives it
// `part` (`encoder`, `display`, `buttons` or `fader`).
import QtQuick
import XTouch
import XTouch.Device

PartPreview {
    required property QtObject form
    // the part of the strip it shows
    property string part

    // `part` is set right after the item is made: until then it has a model of its own
    model: form.previewModel(part)
}
