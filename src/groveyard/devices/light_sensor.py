"""Driver for the Grove light sensor (LM358 photo-resistor module).

The module is a plain analog input: the photo-resistor sits in a divider with a
fixed 10 kΩ resistor, and the board's 10-bit ADC reports the divider's midpoint.
More light lowers the photo-resistor's resistance and *raises* the counts, so raw
counts are already a usable brightness proxy and are what most callers threshold.

On top of the raw value this driver offers the resistance conversion from
``docs/protocol.md`` section 5, which is the only unit the module can be pinned
to without a calibrated reference: ``R = (1023 - adc) * 10 / adc`` kΩ, where a
*higher* resistance means a *darker* environment.
"""

from __future__ import annotations

import math
from typing import Final

from groveyard.devices.base import AnalogInputDevice
from groveyard.protocol.commands import ADC_MAX_COUNTS

SERIES_RESISTANCE_KOHM: Final[float] = 10.0
"""Fixed resistor the photo-resistor forms a divider with, in kilo-ohms."""

DARK_RESISTANCE_KOHM: Final[float] = math.inf
"""Resistance reported at zero counts: the photo-resistor is effectively open."""

MIN_MEASURABLE_COUNTS: Final[int] = 1
"""Lowest reading the resistance formula is defined for; ``0`` divides by zero."""


class LightSensor(AnalogInputDevice):
    """A Grove light sensor plugged into an analog socket.

    Inherits :meth:`~groveyard.devices.base.AnalogInputDevice.read_raw` and
    :meth:`~groveyard.devices.base.AnalogInputDevice.read_ratio`; the raw
    ``0..1023`` reading always stays reachable and the resistance conversion is
    convenience layered on top of it, never a replacement.

    The driver owns no state beyond the configured pin mode (``docs/protocol.md``
    section 6), so its lock exists to keep one logical read — configure-then-read
    — atomic against a concurrent read of the same socket.

    Example:
        ```python
        sensor = LightSensor(board, AnalogPort.A0)
        if await sensor.read_resistance_kohm() > 100.0:
            print("it is dark in here")
        ```
    """

    async def read_resistance_kohm(self) -> float:
        """Read the photo-resistor's resistance.

        Applies ``R = (1023 - adc) * 10 / adc`` kΩ (``docs/protocol.md`` section
        5). The scale is inverse to brightness: a bright room reads a few kΩ, a
        dark one hundreds.

        Returns:
            Resistance in kilo-ohms, ``0.0`` at full scale and
            :data:`DARK_RESISTANCE_KOHM` (``math.inf``) at zero counts.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_resistance_kohm_locked()

    async def _read_resistance_kohm_locked(self) -> float:
        """Read the ADC and convert it to a resistance. Lock held.

        Returns:
            Resistance in kilo-ohms.
        """
        return self._to_resistance_kohm(await self._read_raw_locked())

    def _to_resistance_kohm(self, counts: int) -> float:
        """Convert raw ADC counts to the photo-resistor's resistance.

        Zero counts mean the divider's midpoint sits at ground, which the formula
        cannot express: the implied resistance is unbounded. That is a legitimate
        physical reading (total darkness, or an unplugged module), not a caller
        bug, so it returns :data:`DARK_RESISTANCE_KOHM` rather than raising.
        ``math.inf`` also compares correctly against any "darker than" threshold,
        which is what callers do with this value.

        Args:
            counts: Raw ADC reading in ``0..1023``.

        Returns:
            Resistance in kilo-ohms.
        """
        if counts < MIN_MEASURABLE_COUNTS:
            return DARK_RESISTANCE_KOHM
        return (ADC_MAX_COUNTS - counts) * SERIES_RESISTANCE_KOHM / counts
