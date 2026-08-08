"""Driver for the Grove rotary angle sensor and the linear slide potentiometer.

Both modules are a 10 kΩ potentiometer wired as a voltage divider across the 5 V
rail, so the board's ADC reads their wiper position directly. The normalised
``0.0..1.0`` position inherited from
:class:`~groveyard.devices.base.AnalogInputDevice` is the portable reading; the
angle conversion of ``docs/protocol.md`` section 5 applies to the rotary variant,
whose shaft has 300° of usable travel:

``voltage = adc * Vref / 1023`` and ``degrees = voltage * 300 / Vcc``, with
``Vref = Vcc = 5 V``. Since reference and supply are the same rail, this reduces
to a straight ratio of full travel — the two-step form is kept because that is
how the hardware reference states it.
"""

from __future__ import annotations

from typing import Final

from groveyard.devices.base import AnalogInputDevice
from groveyard.protocol.commands import ADC_MAX_COUNTS

ADC_REFERENCE_VOLTS: Final[float] = 5.0
"""ADC full-scale reference (``Vref``): 1023 counts correspond to this voltage."""

SUPPLY_VOLTS: Final[float] = 5.0
"""Rail the potentiometer is powered from (``Vcc``); its wiper cannot exceed it."""

ROTARY_FULL_TRAVEL_DEGREES: Final[float] = 300.0
"""Mechanical travel of the Grove rotary angle sensor, end stop to end stop."""


class Potentiometer(AnalogInputDevice):
    """A Grove rotary angle sensor or slide potentiometer on an analog socket.

    Inherits :meth:`~groveyard.devices.base.AnalogInputDevice.read_raw` and
    :meth:`~groveyard.devices.base.AnalogInputDevice.read_ratio`, so the raw
    ``0..1023`` reading and the normalised position stay reachable; voltage and
    angle are convenience on top.

    The driver owns no state beyond the configured pin mode (``docs/protocol.md``
    section 6); its lock keeps one logical read — configure-then-read — atomic.

    Note:
        :meth:`read_degrees` assumes the rotary module's
        :data:`ROTARY_FULL_TRAVEL_DEGREES` of travel. On a linear slide
        potentiometer the number is meaningless — use
        :meth:`~groveyard.devices.base.AnalogInputDevice.read_ratio` there.

    Example:
        ```python
        knob = Potentiometer(board, AnalogPort.A2)
        print(f"{await knob.read_degrees():.1f} degrees")
        ```
    """

    async def read_voltage(self) -> float:
        """Read the wiper voltage.

        Applies ``voltage = adc * Vref / 1023`` (``docs/protocol.md`` section 5).

        Returns:
            Volts in ``0.0..5.0``.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_voltage_locked()

    async def read_degrees(self) -> float:
        """Read the shaft angle of the rotary module.

        Applies ``degrees = voltage * 300 / Vcc`` to the wiper voltage
        (``docs/protocol.md`` section 5).

        Returns:
            Degrees in ``0.0..300.0``, measured from the counter-clockwise end
            stop.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_degrees_locked()

    async def _read_voltage_locked(self) -> float:
        """Read the ADC and convert it to volts. Lock held.

        Returns:
            Volts in ``0.0..5.0``.
        """
        return self._to_volts(await self._read_raw_locked())

    async def _read_degrees_locked(self) -> float:
        """Read the ADC and convert it to an angle. Lock held.

        Returns:
            Degrees in ``0.0..300.0``.
        """
        return self._to_degrees(self._to_volts(await self._read_raw_locked()))

    def _to_volts(self, counts: int) -> float:
        """Convert raw ADC counts to the voltage they represent.

        Args:
            counts: Raw ADC reading in ``0..1023``.

        Returns:
            Volts in ``0.0..5.0``.
        """
        return counts * ADC_REFERENCE_VOLTS / ADC_MAX_COUNTS

    def _to_degrees(self, volts: float) -> float:
        """Convert a wiper voltage to a shaft angle.

        Args:
            volts: Wiper voltage, ``0.0`` at one end stop and :data:`SUPPLY_VOLTS`
                at the other.

        Returns:
            Degrees in ``0.0..300.0``.
        """
        return volts * ROTARY_FULL_TRAVEL_DEGREES / SUPPLY_VOLTS
