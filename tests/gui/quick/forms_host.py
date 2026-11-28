"""
A window of its own with one form in it, for the tests of the fields: the pages that show channels and states come
later, so a test hosts the form (`FormView`) itself, in the engine of the window of a `Ui` (same theme, same icons).
"""

from typing import Any

from PyQt6.QtCore import QPointF, QUrl
from PyQt6.QtQml import QQmlComponent
from PyQt6.QtQuick import QQuickItem, QQuickWindow

from tests.support.quick import Ui
from xtouch_daemon.gui.quick.forms.form import Form
from xtouch_daemon.gui.quick.models import KeyedListModel
from xtouch_daemon.gui.quick.pages.settings import AliasesBackend, SettingsPage

HOST = b"""
import QtQuick
import QtQuick.Controls
import XTouch
import XTouch.Forms
ApplicationWindow {
    width: 900; height: 700; visible: true
    color: Theme.colors.surface
    Flickable {
        objectName: "host_flick"
        anchors.fill: parent
        contentHeight: view.height + 40
        clip: true
        FormView { id: view; objectName: "host_view"; x: 20; y: 20; width: parent.width - 40; form: hostForm }
    }
}
"""


def host(ui: Ui, form: Form) -> HostUi:
    """A `Ui` for a window that shows `form`; `form.active` is on."""
    context = ui.engine.rootContext()
    assert context is not None
    context.setContextProperty("hostForm", form)
    component = QQmlComponent(ui.engine)
    component.setData(HOST, QUrl("file:///forms_host.qml"))
    window = component.create()
    assert isinstance(window, QQuickWindow), component.errors()
    form.active = True
    hosted = HostUi(ui.qtbot, ui.app, ui.engine, window)
    ui.qtbot.waitExposed(window)
    hosted.settle()
    return hosted


class HostUi(Ui):
    """A `Ui` of the host window: a click or a focus scrolls the item into view first, where popups have room."""

    def scroll_to(self, name: str) -> None:
        flick = self.item("host_flick")
        item = self.item(name)
        content: QQuickItem = flick.property("contentItem")
        top = item.mapToItem(content, QPointF(0, 0)).y()
        flick.setProperty("contentY", max(0.0, top - 100))
        self.settle()

    def click(self, target: str | QQuickItem, *args: Any, **kwargs: Any) -> None:
        if isinstance(target, str):
            self.scroll_to(target)
        super().click(target, *args, **kwargs)

    def focus(self, target: str | QQuickItem) -> None:
        if isinstance(target, str):
            self.scroll_to(target)
        super().focus(target)


def settings(ui: Ui) -> SettingsPage:
    """The backend of the page Settings (`App.settings` is typed as a QObject for QML)."""
    page = ui.app.settings
    assert isinstance(page, SettingsPage)
    return page


def aliases(ui: Ui) -> AliasesBackend:
    """The backend of the aliases of the page Settings."""
    backend = settings(ui).aliases
    assert isinstance(backend, AliasesBackend)
    return backend


def alias_rows(ui: Ui) -> KeyedListModel:
    """The rows of the aliases, as the list of QML has them."""
    model = aliases(ui).rows
    assert isinstance(model, KeyedListModel)
    return model
