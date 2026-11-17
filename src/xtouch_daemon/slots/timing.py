"""
A value that follows its input after delays: `delay_on` of states, `delay_off`, `absent_after` of channels.
"""


class Delayed:
    """
    A boolean that turns on `delay_on` seconds after its input turned on, and off `delay_off` seconds after it turned
    off. An input that turns back before that changes nothing. The first update is the baseline: it takes the input
    as it is, without delay.
    """

    def __init__(self, delay_on: float, delay_off: float):
        self.delay_on = delay_on
        self.delay_off = delay_off
        self.value = False
        self._started = False
        self._pending: tuple[bool, float] | None = None
        """The value the input has had since when, while it differs from `value`."""

    def update(self, raw: bool, now: float) -> bool:
        """Takes the input at `now`; whether the value changed (an edge; the baseline is none)."""
        if not self._started:
            self._started = True
            self.value = raw
            return False
        if raw == self.value:
            self._pending = None
            return False
        if self._pending is None:
            self._pending = (raw, now)
        if now - self._pending[1] >= (self.delay_on if raw else self.delay_off):
            self.value = raw
            self._pending = None
            return True
        return False

    def carry(self, before: Delayed) -> None:
        """Goes on from where `before` was (a reload), with its own delays."""
        self.value = before.value
        self._started = before._started
        self._pending = before._pending

    def deadline(self) -> float | None:
        """When a pending change takes effect if the input stays as it is, None without one."""
        if self._pending is None:
            return None
        raw, since = self._pending
        return since + (self.delay_on if raw else self.delay_off)
