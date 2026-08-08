"""Driver for the Grove DHT temperature and humidity sensor.

The DHT family speaks a timing-critical single-wire protocol that the Raspberry
Pi cannot service reliably from Python. The bridge firmware therefore does the
whole exchange itself: command ``40`` takes the pin and the sensor variant, waits
its ~250 ms, and hands back two little-endian ``float32`` values
(``docs/protocol.md`` section 3 and "DHT decoding").

Everything below the driver is already handled elsewhere and is deliberately not
repeated here: the transaction shape, the settle delay, the not-ready retries and
the sanity gate that rejects ``NaN`` or physically impossible values all live in
:class:`~groveyard.protocol.bridge.BridgeProtocol`. This module adds only what a
*device* owns — its variant, its cached last reading, and the lock that keeps that
cache consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from groveyard.devices.base import BridgedDevice
from groveyard.ports import DigitalPort
from groveyard.protocol.commands import DhtVariant

if TYPE_CHECKING:
    from groveyard.board import Board

FAHRENHEIT_SCALE: Final[float] = 9.0 / 5.0
"""Degrees Fahrenheit per degree Celsius."""

FAHRENHEIT_FREEZING_POINT: Final[float] = 32.0
"""Fahrenheit value of 0 °C, the offset of the Celsius-to-Fahrenheit conversion."""


@dataclass(frozen=True, slots=True)
class DhtReading:
    """One temperature and humidity measurement.

    A value object rather than a bare tuple: the two floats have different units
    and are easy to swap by accident, and a named type makes the cached reading on
    :class:`Dht` self-describing. Immutable, so handing it to another task cannot
    tear it.

    Attributes:
        temperature_celsius: Air temperature in degrees Celsius. Within
            ``-40..80 °C`` — anything else is rejected as a failed read by the
            protocol layer (``docs/protocol.md`` section 3).
        humidity_percent: Relative humidity in percent, within ``0..100 %``.
    """

    temperature_celsius: float
    humidity_percent: float

    @property
    def temperature_fahrenheit(self) -> float:
        """Air temperature in degrees Fahrenheit, converted from Celsius.

        Returns:
            The temperature in °F.
        """
        return self.temperature_celsius * FAHRENHEIT_SCALE + FAHRENHEIT_FREEZING_POINT


class Dht(BridgedDevice[DigitalPort]):
    """A DHT11 or DHT22 temperature and humidity sensor on a digital socket.

    The port needs **no** ``pin_mode`` call. Command ``40`` is a self-contained
    firmware operation: the sketch drives the pin in both directions during the
    single-wire exchange (``dht.begin(pin, type)`` and the library's own reads), so
    a direction configured from the host would be overwritten immediately and the
    board's pin-mode cache would then describe a pin the firmware has since
    flipped. The driver therefore never calls
    :meth:`~groveyard.devices.base.BridgedDevice._ensure_mode_locked`; the sensor
    variant is passed per command instead, which is also why the firmware needs it
    on every read.

    A reading takes roughly 250 ms, and the sensors themselves only refresh every
    one to two seconds, so callers should poll slowly and use
    :attr:`last_reading` in between.

    Example:
        ```python
        sensor = Dht(board, DigitalPort.D7)
        reading = await sensor.read()
        print(reading.temperature_celsius, reading.humidity_percent)
        ```
    """

    def __init__(self, board: Board, port: DigitalPort, variant: DhtVariant = DhtVariant.DHT11) -> None:
        """Claim the socket and record which sensor is plugged into it.

        Args:
            board: The connection this device operates on.
            port: The digital socket the sensor is plugged into.
            variant: Which DHT is connected. Defaults to
                :attr:`~groveyard.protocol.commands.DhtVariant.DHT11`, the blue
                module that ships with the starter kit; pass
                :attr:`~groveyard.protocol.commands.DhtVariant.DHT22` for the
                white one.

        Raises:
            PortInUseError: If another live device already holds that socket.
        """
        super().__init__(board, port)
        self._variant = variant
        self._last_reading: DhtReading | None = None

    @property
    def variant(self) -> DhtVariant:
        """The sensor variant this driver tells the firmware to decode."""
        return self._variant

    @property
    def last_reading(self) -> DhtReading | None:
        """The most recent successful reading, or ``None`` before the first one.

        Costs no bus traffic. This is exactly the state the per-device lock
        protects: it is replaced in one assignment, and only after a read has
        succeeded, so a failed or cancelled read leaves the previous value intact
        and no observer ever sees a half-updated measurement.
        """
        return self._last_reading

    async def read(self) -> DhtReading:
        """Measure temperature and humidity.

        Takes about 250 ms, of which the settle delay happens inside the bus
        session (``docs/protocol.md`` section 3). The protocol layer gates the
        result, so a returned reading is always a plausible one and a failed
        single-wire exchange surfaces as ``DeviceNotReadyError`` instead.

        Returns:
            The new reading, which also becomes :attr:`last_reading`.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If every attempt produced an implausible reading.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_locked()

    async def _read_locked(self) -> DhtReading:
        """Run one DHT command and refresh the cache. Lock held.

        The cache is written only after the board answered, so an exception on the
        bus cannot leave :attr:`last_reading` describing a measurement that never
        happened.

        Returns:
            The reading the board reported.
        """
        self._require_open()
        celsius, humidity = await self._board.dht_read(self._port, self._variant)
        reading = DhtReading(temperature_celsius=celsius, humidity_percent=humidity)
        self._last_reading = reading
        return reading
