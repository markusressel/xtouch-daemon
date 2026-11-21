"""
`[controls]` bound to entities of Home Assistant: an encoder that sets one, what the slot shows of others, a button
that calls a service. Home Assistant is the one in memory.
"""

from collections.abc import AsyncIterator

import pytest

from tests.support.audio import output
from tests.support.hardware import RecordingSurface
from tests.support.homeassistant import FakeHomeAssistant, connected
from tests.support.slots import Rig
from tests.support.tasks import settle
from xtouch_daemon.audio.model import AudioState
from xtouch_daemon.config.files import parse_config
from xtouch_daemon.hardware import protocol
from xtouch_daemon.hardware.protocol import Button, Color, Led, RingMode
from xtouch_daemon.homeassistant.client import HomeAssistant
from xtouch_daemon.system.commands import Commands

CONFIG = """
[homeassistant]
url = "http://ha.test:8123"
token = "the-token"

[voip]
provider = "demo"

[channel.out]
type = "output"
device = "speaker"
label = "Speaker"

[slots]
1 = "out"

[controls.1]
encoder = { entity = "media_player.tv", step = 0.1 }
lcd = { entity = "media_player.tv", attribute = "media_title" }
color = { entity = "light.desk" }
meter = { entity = "sensor.cpu" }
rec = { press = { service = "light.toggle", entity = "light.desk" }, led = { entity = "light.desk" } }
"""

STATE = AudioState(outputs=(output("speaker", 50),), default_output="speaker")


@pytest.fixture
async def hass() -> AsyncIterator[tuple[FakeHomeAssistant, HomeAssistant]]:
    home = FakeHomeAssistant()
    home.set("media_player.tv", "playing", volume_level=0.5, media_title="Song 2")
    home.set("light.desk", "on", rgb_color=[0, 255, 0])
    home.set("sensor.cpu", "50")
    hass = await connected(home)
    yield home, hass
    await hass.close()


async def test_controls_set_and_show_entities(
    surface: RecordingSurface, hass: tuple[FakeHomeAssistant, HomeAssistant]
) -> None:
    home, connection = hass
    commands = Commands(connection)
    rig = Rig(surface, parse_config(CONFIG), commands=commands)
    rig.step(STATE)
    await settle()
    claim = rig.desk.claims[0]
    assert claim is not None
    assert claim.taken == frozenset({"encoder", "rec"})
    device = surface.strips[0]
    assert device.text == ["Speaker", "Song 2"]
    assert device.color == Color.GREEN
    assert device.leds[Button.REC] == Led.ON
    assert device.ring == (6, RingMode.WRAP)
    rig.desk.show_meters()
    assert surface.meters(0) == [round(0.5 * protocol.METER_MAX)]
    surface.on_event(protocol.EncoderTurned(0, 1))
    await settle()
    assert home.calls == [("media_player.volume_set", {"volume_level": 0.6}, "media_player.tv")]
    surface.on_event(protocol.ButtonPressed(0, Button.REC, True))
    await settle()
    assert home.calls[-1] == ("light.toggle", {}, "light.desk")
    home.set("light.desk", "off")
    await settle()
    assert device.color == Color.BLACK
    assert device.leds[Button.REC] == Led.OFF
    rig.mixer.close()
    await commands.wait_closed()
    assert connection.watched == 0
