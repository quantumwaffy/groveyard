"""Driver for the Grove sound sensor (electret microphone with an envelope stage).

The module reports a noisy analog *envelope* of the ambient sound level, not a
calibrated dB value, so there is no unit conversion to offer: raw ADC counts are
the reading, and callers threshold them (``docs/protocol.md`` section 5).

What the driver does add is the averaging window that section 5 recommends for
this module. Averaging is a multi-transaction operation, which makes it the
textbook case for the per-device lock: the samples of one window must belong to
one window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from groveyard.devices.base import AnalogInputDevice

if TYPE_CHECKING:
    from groveyard.board import Board
    from groveyard.ports import AnalogPort

DEFAULT_WINDOW_SIZE: Final[int] = 8
"""Samples per averaged read: enough to smooth the envelope, ~16 ms of bus time."""

MIN_WINDOW_SIZE: Final[int] = 1
"""Smallest sensible window; a window of one is simply an unaveraged read."""


class SoundSensor(AnalogInputDevice):
    """A Grove sound sensor plugged into an analog socket.

    Inherits :meth:`~groveyard.devices.base.AnalogInputDevice.read_raw` and
    :meth:`~groveyard.devices.base.AnalogInputDevice.read_ratio`, so the raw
    ``0..1023`` envelope is always reachable; :meth:`read_average` is the smoothed
    convenience on top.

    The driver owns the averaging window besides the configured pin mode
    (``docs/protocol.md`` section 6).

    Example:
        ```python
        mic = SoundSensor(board, AnalogPort.A1, window_size=16)
        if await mic.read_average() > 400.0:
            print("someone clapped")
        ```
    """

    def __init__(self, board: Board, port: AnalogPort, window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        """Claim an analog socket for a sound sensor.

        Args:
            board: The connection this device operates on.
            port: The analog socket the module is plugged into.
            window_size: Number of samples :meth:`read_average` takes. Must be at
                least :data:`MIN_WINDOW_SIZE`.

        Raises:
            ValueError: If ``window_size`` is smaller than :data:`MIN_WINDOW_SIZE`.
            PortInUseError: If another live device already holds that socket.
        """
        if window_size < MIN_WINDOW_SIZE:
            msg = f"window_size must be at least {MIN_WINDOW_SIZE}, got {window_size}"
            raise ValueError(msg)
        super().__init__(board, port)
        self._window_size = window_size

    @property
    def window_size(self) -> int:
        """Number of samples :meth:`read_average` takes per call."""
        return self._window_size

    async def read_average(self) -> float:
        """Read :attr:`window_size` consecutive samples and return their mean.

        The whole window is one logical operation and is taken under the device
        lock from first sample to last, so two tasks averaging the same sensor
        cannot mix their samples into each other's result.

        Each sample is its own bridged transaction (``docs/protocol.md`` section
        2), so the *bus* lock is taken and released ``window_size`` times, each
        time for about 2 ms. Other devices are therefore not blocked for the
        duration of the window: they only contend for the bus between samples,
        exactly as they would with any other read.

        Returns:
            Mean raw counts over the window, in ``0.0..1023.0``.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If a reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_average_locked()

    async def _read_average_locked(self) -> float:
        """Sample the window and average it. Lock held.

        Calls :meth:`~groveyard.devices.base.AnalogInputDevice._read_raw_locked`
        rather than the public ``read_raw``: :class:`asyncio.Lock` is not
        reentrant, so taking it again here would deadlock the task.

        Returns:
            Mean raw counts over the window.
        """
        total = 0
        for _ in range(self._window_size):
            total += await self._read_raw_locked()
        return total / self._window_size
