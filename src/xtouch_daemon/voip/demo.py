"""
A voice chat that is not there: the participants of the configuration talk in turns, and their volumes and mutes are
kept in memory. To try `voip` strips (and layouts with them) without a voice chat.
"""

import asyncio
import dataclasses
import math

from xtouch_daemon.voip.provider import Capability, Participant, VoipProvider

TICK = 0.1
"""How often the levels change."""
TURN = 3.0
"""Seconds each participant talks, before the next one (and a pause after the last one)."""


class DemoProvider(VoipProvider):
    name = "demo"

    def __init__(self, names: tuple[str, ...]):
        super().__init__(frozenset(Capability))
        self._people = tuple(Participant(str(number), name) for number, name in enumerate(names, start=1))
        self.update(self._people)

    def tick(self, now: float) -> None:
        """The state at `now` (seconds): who talks (one after the other, then a pause), and how loud."""
        turn = int(now / TURN) % (len(self._people) + 1)
        level = 0.35 + 0.6 * abs(math.sin(now * 7))
        self.update(
            tuple(
                dataclasses.replace(
                    person,
                    # as in Mumble: a muted participant still talks, but their voice doesn't come
                    talking=index == turn,
                    level=min(1.0, level * person.volume / 100) if index == turn and not person.muted else 0.0,
                    pre_fader_level=level if index == turn and not person.muted else 0.0,
                )
                for index, person in enumerate(self._people)
            )
        )

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            self.tick(loop.time())
            await asyncio.sleep(TICK)

    def _change(self, changed: Participant) -> None:
        self._people = tuple(changed if person.id == changed.id else person for person in self._people)
        self.update(
            tuple(
                dataclasses.replace(now, volume=person.volume, muted=person.muted)
                for now, person in zip(self.participants, self._people, strict=True)
            )
        )

    def _person(self, participant_id: str) -> Participant:
        return next(person for person in self._people if person.id == participant_id)

    async def set_volume(self, participant_id: str, volume: int) -> None:
        self._change(dataclasses.replace(self._person(participant_id), volume=volume))

    async def set_muted(self, participant_id: str, muted: bool) -> None:
        self._change(dataclasses.replace(self._person(participant_id), muted=muted))
