"""
The drawing of the device in Qt Quick: the strips, painted by items of QML with the painting of the widgets, the
window Device with the live view of the daemon, the preview, the test and the virtual device, and the preview of a
part of a strip for the forms. See `docs/development/design/qml.md`.
"""

from xtouch_daemon.gui.quick.device.items import register_types

register_types()
