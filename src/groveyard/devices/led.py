"""Driver for the Grove LED, with on/off and PWM brightness.

The LED is a digital output that the firmware can also drive with an 8-bit PWM
duty cycle through command ``4`` (``docs/protocol.md`` section 3: ``[4, pin,
value, 0]`` with ``value`` in ``0..255``, no reply). Section 6 lists "on/off +
brightness" as the state this driver owns, and that pair is exactly why the
per-device lock matters here: brightness and on/off are two views of one cached
value, updated by a read-modify-write that spans a bus transaction.

Hardware note: only the PWM-capable digital sockets (``D3``, ``D5``, ``D6`` on a
GrovePi+) dim continuously. On the remaining digital sockets the firmware's
``analogWrite`` degrades to a plain level, so the LED is simply on or off — the
API is unchanged, the intermediate steps are just not visible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from groveyard.devices.base import DigitalOutputDevice
from groveyard.ports import PinMode
from groveyard.protocol.commands import PWM_MAX_DUTY

if TYPE_CHECKING:
    from groveyard.board import Board
    from groveyard.ports import DigitalPort

MIN_BRIGHTNESS: Final[float] = 0.0
"""Darkest commandable brightness; maps to a PWM duty cycle of ``0``."""

MAX_BRIGHTNESS: Final[float] = 1.0
"""Brightest commandable brightness; maps to a PWM duty cycle of ``PWM_MAX_DUTY``."""

PWM_OFF_DUTY: Final[int] = 0
"""Duty cycle at which the LED emits no light at all."""


class Led(DigitalOutputDevice):
    """An LED on a digital socket, switchable and dimmable.

    On/off and brightness are the *same* state, so the driver keeps one cached
    ratio and derives everything from it:

    * :meth:`on` drives full brightness (``1.0``);
    * :meth:`off` drives ``0.0``, which also clears the cached brightness, so a
      later :meth:`on` never resurrects a previous dim level;
    * :meth:`~groveyard.devices.base.DigitalOutputDevice.toggle` flips between the
      two, treating any non-zero brightness as "on".

    That choice keeps the model unambiguous: the cached brightness is always the
    ratio the hardware was last told to hold, never a remembered preference.

    Example:
        ```python
        led = Led(board, DigitalPort.D5)
        await led.set_brightness(0.25)
        await led.off()
        ```
    """

    def __init__(self, board: Board, port: DigitalPort) -> None:
        """Claim the socket and assume the LED is dark.

        The assumption is made true by the first write and by :meth:`close`, which
        always leaves the socket low.

        Args:
            board: The connection this device operates on.
            port: The digital socket the LED is plugged into.

        Raises:
            PortInUseError: If another live device already holds that socket.
        """
        super().__init__(board, port)
        self._brightness = MIN_BRIGHTNESS

    @property
    def brightness(self) -> float:
        """The brightness this driver last commanded, in ``0.0..1.0``.

        Read from the cache, so it costs no bus traffic. It reflects the last
        *successful* write: a failed write leaves the previous value in place
        rather than claiming a state the hardware is not in.
        """
        return self._brightness

    async def set_brightness(self, value: float) -> None:
        """Dim the LED to a fraction of full brightness.

        The requested ratio is scaled to the firmware's 8-bit duty cycle and sent
        as one ``analog_write`` (``docs/protocol.md`` section 3). Reading and
        updating the cached brightness happens under the device lock together with
        that write, so two tasks dimming the same LED cannot leave the cache
        describing a level the hardware is not holding.

        Args:
            value: Brightness ratio in ``0.0`` (dark) to ``1.0`` (full).

        Raises:
            ValueError: If ``value`` is outside ``0.0..1.0`` or is ``NaN``.
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        self._validate_brightness(value)
        async with self._lock:
            await self._set_brightness_locked(value)

    async def _set_brightness_locked(self, value: float) -> None:
        """Drive the LED to a validated brightness ratio. Lock held.

        The cache is updated only after the write succeeds. ``is_on`` is derived
        from the duty cycle rather than from the requested ratio, so a ratio that
        rounds down to zero is reported honestly as "off".

        Args:
            value: Brightness ratio in ``0.0..1.0``, already validated.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        self._require_open()
        await self._ensure_mode_locked(PinMode.OUTPUT)
        duty = self._to_duty(value)
        await self._board.analog_write(self._port, duty)
        self._brightness = value
        self._is_on = duty > PWM_OFF_DUTY

    async def _set_state_locked(self, *, state: bool) -> None:
        """Switch the LED fully on or fully off. Lock held.

        Overrides the digital-write of the base class so that on/off and
        brightness stay one state: switching on means "brightness ``1.0``" and
        switching off means "brightness ``0.0``".

        Args:
            state: ``True`` for full brightness, ``False`` for dark.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        await self._set_brightness_locked(MAX_BRIGHTNESS if state else MIN_BRIGHTNESS)

    async def _shutdown_locked(self) -> None:
        """Leave the LED dark and forget the brightness. Lock held.

        Delegates to the base class, which drives the socket low with a plain
        digital write: that is the safest possible final state, because it also
        stops any PWM the firmware was generating.
        """
        await super()._shutdown_locked()
        self._brightness = MIN_BRIGHTNESS

    def _to_duty(self, value: float) -> int:
        """Scale a brightness ratio to the firmware's 8-bit duty cycle.

        Args:
            value: Brightness ratio in ``0.0..1.0``, already validated.

        Returns:
            A duty cycle in ``0..PWM_MAX_DUTY``.
        """
        return round(value * PWM_MAX_DUTY)

    def _validate_brightness(self, value: float) -> None:
        """Reject a brightness the hardware cannot represent.

        Checked before the lock is taken: an out-of-range argument is a caller bug
        (see :mod:`groveyard.errors`), so it should not queue behind other tasks
        or touch the bus. The comparison also rejects ``NaN``, which would
        otherwise scale to a meaningless duty cycle.

        Args:
            value: Brightness ratio the caller asked for.

        Raises:
            ValueError: If ``value`` is outside ``0.0..1.0`` or is ``NaN``.
        """
        if not MIN_BRIGHTNESS <= value <= MAX_BRIGHTNESS:
            msg = f"brightness must be in {MIN_BRIGHTNESS}..{MAX_BRIGHTNESS}, got {value}"
            raise ValueError(msg)
