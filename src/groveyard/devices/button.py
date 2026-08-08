"""Driver for the Grove momentary push button.

The button is the simplest bridged module there is: a digital input whose level
the firmware reports with command ``1`` (``docs/protocol.md`` section 3, and the
module catalog in section 6). The board pulls the signal low while the button is
released and the module drives it high while the button is held, so "pressed" is
exactly "reads ``1``".

Everything mechanical — the pin-mode setup, the read itself and the per-device
lock that keeps them together — already lives in
:class:`~groveyard.devices.base.DigitalInputDevice`. This module adds nothing but
the vocabulary of a button, which is precisely how thin a driver should be.
"""

from __future__ import annotations

from groveyard.devices.base import DigitalInputDevice


class Button(DigitalInputDevice):
    """A momentary push button plugged into a digital socket.

    The driver is stateless beyond the port's cached pin mode: every call asks the
    board for the level right now, because a button has no state worth caching —
    it can change between any two reads.

    Debouncing is deliberately not implemented (YAGNI): a bridged read already
    costs a bus round trip of a few milliseconds, which swallows most contact
    bounce, and applications that need edge detection want their own policy.

    Example:
        ```python
        button = Button(board, DigitalPort.D3)
        if await button.is_pressed():
            await led.on()
        ```
    """

    async def is_pressed(self) -> bool:
        """Report whether the button is being held down right now.

        One bridged ``digital_read`` (``docs/protocol.md`` section 3), taken under
        the device lock by :meth:`~groveyard.devices.base.DigitalInputDevice.read_value`.
        The Grove button reads ``1`` while held and ``0`` while released.

        Returns:
            ``True`` while the button is held down.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        return await self.is_high()
