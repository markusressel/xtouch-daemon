"""
The options of `[behavior]` and `[switching]` that only strips and layouts have: channels, states and slots have
`[pool.auto] hold` and `exclude`, `absent_after` and `delay_off` instead.
"""

from typing import Annotated

from pydantic import Field

from xtouch_daemon.config.names import StreamNames
from xtouch_daemon.config.sections import BehaviorConfig, SwitchingConfig


class LegacyBehaviorConfig(BehaviorConfig):
    auto_hold: Annotated[float, Field(ge=0)] = 5.0
    """
    Seconds an `auto` strip keeps an application after it stopped playing, so a music player does not jump to
    another strip between two tracks.
    """
    ignore: StreamNames = ("speech-dispatcher",)
    """
    Applications that `auto` strips never take: parts of the name or binary, ignoring case, e.g. "notification" for
    notification sounds, or presets like `@games`.
    """
    collapse_hold: Annotated[float, Field(ge=0)] = 3.0
    """
    Seconds a strip with `collapse` keeps its fader after it has nothing to control anymore, before the strips after
    it move up. It comes back at once.
    """


class LegacySwitchingConfig(SwitchingConfig):
    hold: Annotated[float, Field(ge=0)] = 10.0
    """
    Seconds a layout stays after its rule stopped matching (`apps`, `processes`), e.g. while a game loads the next
    level.
    """
