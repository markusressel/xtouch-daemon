from pathlib import Path

from xtouch_daemon.gui.domain.voip import install_hint, install_steps
from xtouch_daemon.mumble import Setup


def test_what_install_does():
    assert install_hint(Setup(None, False, None, False)).startswith("Mumble is not installed")
    assert install_hint(Setup(None, False, None, True)).startswith("There is no plugin to install")
    assert install_hint(Setup(None, True, None, True)).startswith("Builds the plugin")
    assert install_hint(Setup(Path("/b"), False, None, True)).startswith("Opens it")


def test_the_steps_say_whether_mumble_has_the_plugin():
    assert install_steps(Setup(None, True, None, True))[0].endswith("Mumble asks: confirm.")
    assert "(/p/libxtouch-daemon.so)" in install_steps(Setup(None, True, Path("/p/libxtouch-daemon.so"), True))[0]
