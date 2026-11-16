"""The participants of a voice chat for `voip` strips, from a provider (see `provider.py`)."""

from pathlib import Path
from typing import assert_never

from xtouch_daemon.config import VoipConfig
from xtouch_daemon.voip.bridge import BridgeProvider
from xtouch_daemon.voip.demo import DemoProvider
from xtouch_daemon.voip.provider import Capability, Participant, VoipProvider

__all__ = ["Capability", "Participant", "VoipProvider", "build_provider"]


def build_provider(config: VoipConfig, socket: Path) -> VoipProvider:
    """The provider of the `[voip]` section; `socket` is where the `bridge` one waits for its plugin."""
    match config.provider:
        case "demo":
            return DemoProvider(config.participants)
        case "bridge":
            return BridgeProvider(socket)
        case _ as unreachable:
            assert_never(unreachable)
