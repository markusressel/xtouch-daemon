// The options of the place of the candidate picked ("Look in slot N": the color, the encoder, the meter, ... of this
// candidate only) as the rows of the forms. `slots.placeForm` has them: every option is optional here, unset it is
// as on the channel or in the pool, and its row says so.
import QtQuick
import XTouch
import XTouch.Forms

FormView {
    required property QtObject slots
    objectName: "place_form"
    form: slots.placeForm
}
