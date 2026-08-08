"""Driver for the Grove piezo buzzer.

The buzzer is a plain digital output (``docs/protocol.md`` section 6): the
firmware's ``digital_write`` command ``2`` drives the socket high to sound it and
low to silence it (section 3). On top of on/off the driver offers a timed beep,
which is the one thing an actuator like this must get right under cancellation —
a task that is cancelled mid-beep must still leave the buzzer silent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from groveyard.devices.base import DigitalOutputDevice
from groveyard.errors import GroveyardError

MIN_BEEP_SECONDS: Final[float] = 0.0
"""Exclusive lower bound for a beep: a zero-length beep is a caller bug."""

_LOGGER: Final = logging.getLogger(__name__)


class Buzzer(DigitalOutputDevice):
    """A piezo buzzer on a digital socket.

    Beyond the inherited on/off it adds :meth:`beep`, a self-terminating sound.
    The whole beep runs under the device lock, so a concurrent task cannot switch
    the buzzer on behind its back and be silenced by the beep's own cleanup — or,
    worse, silence itself and leave the beep's "on" as the last word.

    Example:
        ```python
        buzzer = Buzzer(board, DigitalPort.D2)
        await buzzer.beep(0.2)
        ```
    """

    async def beep(self, seconds: float) -> None:
        """Sound the buzzer for a fixed time, then silence it.

        Two bridged ``digital_write`` commands with an awaited delay in between
        (``docs/protocol.md`` section 3); the delay is a plain
        :func:`asyncio.sleep`, so the event loop stays free for other devices.

        The device lock is held for the whole beep, which makes the sound
        atomic with respect to other operations on *this* buzzer: concurrent calls
        queue instead of overlapping. Other devices are unaffected, because the bus
        is only held for the two writes themselves.

        Cancelling the beep is safe. The silencing write runs from a ``finally``
        block and is *shielded*, so a second cancellation — a repeated
        ``Task.cancel``, a collapsing :class:`asyncio.TaskGroup`, loop shutdown —
        cannot abort the write itself and leave the buzzer screaming. The
        cancellation is then re-raised unchanged: swallowing it would break
        structured concurrency for every enclosing task group and timeout. A
        transport failure during that write is logged rather than allowed to
        replace the cancellation.

        Args:
            seconds: How long to sound, in seconds. Must be greater than zero.

        Raises:
            ValueError: If ``seconds`` is not greater than zero, or is ``NaN``.
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus failed while the beep was running normally.
        """
        self._validate_duration(seconds)
        async with self._lock:
            await self._set_state_locked(state=True)
            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                await self._silence_after_cancellation_locked()
                raise
            else:
                await self._set_state_locked(state=False)

    async def _silence_after_cancellation_locked(self) -> None:
        """Silence the buzzer while the task is being cancelled. Lock held.

        Shielded so the write survives further cancellation, and tolerant of a bus
        failure: there is nothing useful left to do with that error at this point,
        and raising it would hide the cancellation the caller is waiting for.
        """
        try:
            await asyncio.shield(self._set_state_locked(state=False))
        except GroveyardError:
            _LOGGER.warning("%s could not be silenced after cancellation", self.describe(), exc_info=True)

    def _validate_duration(self, seconds: float) -> None:
        """Reject a beep duration that makes no physical sense.

        Checked before the lock is taken: an out-of-range argument is a caller bug
        (see :mod:`groveyard.errors`), so it should neither wait for the lock nor
        reach the bus. The comparison also rejects ``NaN``, which would otherwise
        make :func:`asyncio.sleep` behave unpredictably.

        Args:
            seconds: Duration the caller asked for.

        Raises:
            ValueError: If ``seconds`` is not greater than zero, or is ``NaN``.
        """
        if not seconds > MIN_BEEP_SECONDS:
            msg = f"beep duration must be greater than {MIN_BEEP_SECONDS} seconds, got {seconds}"
            raise ValueError(msg)
