"""Driver for the Grove ultrasonic ranger.

The module measures distance by timing an ultrasonic echo, which needs
microsecond-accurate pulse handling. The bridge firmware does that: command ``7``
triggers the ping, times the echo with a bounded ``pulseIn`` and returns the
distance in centimetres as a big-endian 16-bit word (``docs/protocol.md``
section 3).

The ~50 ms the firmware needs sits inside the bus session in
:class:`~groveyard.protocol.bridge.BridgeProtocol`, so this driver never sleeps.
What it adds is device-level meaning: the sensor's usable range, and the cached
last distance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from groveyard.devices.base import BridgedDevice
from groveyard.ports import DigitalPort

if TYPE_CHECKING:
    from groveyard.board import Board

ULTRASONIC_MIN_DISTANCE_CM: Final[int] = 3
"""Closest distance the module can resolve; below this the echo returns too early."""

ULTRASONIC_MAX_DISTANCE_CM: Final[int] = 400
"""Furthest distance the module can resolve; beyond this no echo comes back in time."""


class Ultrasonic(BridgedDevice[DigitalPort]):
    """An ultrasonic ranger on a digital socket.

    The port needs **no** ``pin_mode`` call. Command ``7`` is a self-contained
    firmware operation: the sketch drives the pin as an output to emit the trigger
    pulse and immediately switches it to an input to time the echo, so a direction
    configured from the host would be overwritten and the board's pin-mode cache
    would then describe a pin the firmware has since flipped. The driver therefore
    never calls
    :meth:`~groveyard.devices.base.BridgedDevice._ensure_mode_locked`.

    Out-of-range results are reported as *absence of a measurement*, not as an
    error: the firmware's echo timeout yields ``0`` when nothing is in front of the
    sensor, and readings outside ``3..400 cm`` are physically meaningless
    (``docs/protocol.md`` section 3). "Nothing in range" is a normal, expected
    outcome for a ranger, so :meth:`read_distance_cm` returns ``None`` for it while
    :meth:`read_raw_distance_cm` still exposes exactly what the board said.
    Genuine faults keep raising, as everywhere else in the library.

    Distances are whole centimetres because that is the firmware's own resolution:
    it divides the echo duration down to an integer before sending it.

    Example:
        ```python
        ranger = Ultrasonic(board, DigitalPort.D5)
        distance = await ranger.read_distance_cm()
        if distance is not None:
            print(f"{distance} cm")
        ```
    """

    def __init__(self, board: Board, port: DigitalPort) -> None:
        """Claim the socket for the ranger.

        Args:
            board: The connection this device operates on.
            port: The digital socket the ranger is plugged into.

        Raises:
            PortInUseError: If another live device already holds that socket.
        """
        super().__init__(board, port)
        self._last_distance_cm: int | None = None

    @property
    def last_distance_cm(self) -> int | None:
        """Distance of the most recent ping, in centimetres.

        ``None`` means the last ping found nothing within ``3..400 cm``, or that no
        ping has been made yet. Costs no bus traffic. This is the state the
        per-device lock protects: it is replaced in one assignment at the end of a
        measurement, so concurrent readers never observe a value from a ping that
        is still in flight.
        """
        return self._last_distance_cm

    async def read_distance_cm(self) -> int | None:
        """Ping and return the distance to the nearest obstacle.

        The measurement takes about 50 ms, which the protocol layer waits for
        inside the bus session (``docs/protocol.md`` section 3).

        Returns:
            The distance in whole centimetres within ``3..400``, or ``None`` if
            nothing in that range echoed back.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_distance_locked()

    async def read_raw_distance_cm(self) -> int:
        """Ping and return exactly what the firmware reported, ungated.

        Useful for diagnostics: ``0`` shows the echo timed out, and an absurdly
        large value shows the ranger is mis-wired or the reply was mistimed. The
        cache is updated the same way as for :meth:`read_distance_cm`, so the two
        methods can be mixed freely.

        Returns:
            The raw distance in centimetres as the board computed it, which may lie
            outside ``3..400``.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_raw_locked()

    async def _read_distance_locked(self) -> int | None:
        """Ping once and report the range-gated result. Lock held.

        Returns:
            The distance in centimetres, or ``None`` if it was out of range.
        """
        await self._read_raw_locked()
        return self._last_distance_cm

    async def _read_raw_locked(self) -> int:
        """Ping once, refresh the cache and report the raw result. Lock held.

        Both public reads funnel through here, so the cache is written in exactly
        one place and always after the board has answered: a failed transaction
        leaves the previous distance untouched.

        Returns:
            The raw distance in centimetres reported by the firmware.
        """
        self._require_open()
        raw_cm = await self._board.ultrasonic_read(self._port)
        self._last_distance_cm = raw_cm if self._is_in_range(raw_cm) else None
        return raw_cm

    def _is_in_range(self, distance_cm: int) -> bool:
        """Report whether a raw distance is a physically meaningful measurement.

        Args:
            distance_cm: Raw distance reported by the firmware, in centimetres.

        Returns:
            ``True`` if the value lies within the module's ``3..400 cm`` range.
        """
        return ULTRASONIC_MIN_DISTANCE_CM <= distance_cm <= ULTRASONIC_MAX_DISTANCE_CM
