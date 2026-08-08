"""Driver for the Grove relay.

Electrically the relay is the same digital output as an LED or a buzzer
(``docs/protocol.md`` sections 3 and 6): ``digital_write`` command ``2`` drives
the socket high to energise the coil and low to release it. What it adds is
vocabulary — a relay is described by what its contacts do, not by a logic level —
and a stronger reason to fail safe, since the load on the other side is usually
not a 20 mA LED.
"""

from __future__ import annotations

from groveyard.devices.base import DigitalOutputDevice


class Relay(DigitalOutputDevice):
    """A normally-open relay on a digital socket.

    The switching vocabulary is deliberately spelled out in full —
    :meth:`close_circuit`, :meth:`open_circuit`, :attr:`is_closed_circuit` — for
    one reason: :attr:`~groveyard.devices.base.Device.is_closed` already means
    "this *driver* has been closed and released its port". The two senses of
    "closed" are unrelated and must never be confused:

    * :attr:`is_closed_circuit` — the coil is energised and the contacts conduct;
    * :attr:`~groveyard.devices.base.Device.is_closed` — the driver is shut down,
      and (because closing de-energises the coil) the contacts are *open*.

    The inherited on/off API remains available and means the same thing: "on" is
    energised. Closing the driver, or disconnecting the board, drives the socket
    low, so a crashed or cancelled program cannot leave a load switched on.

    Example:
        ```python
        relay = Relay(board, DigitalPort.D6)
        await relay.close_circuit()
        assert relay.is_closed_circuit and not relay.is_closed
        ```
    """

    @property
    def is_closed_circuit(self) -> bool:
        """Whether the contacts are conducting, per the driver's cached state.

        Read from the cache, so it costs no bus traffic. Not to be confused with
        :attr:`~groveyard.devices.base.Device.is_closed`, which reports the
        driver's lifecycle rather than the contacts.
        """
        return self.is_on

    async def close_circuit(self) -> None:
        """Energise the coil so the contacts conduct.

        One bridged ``digital_write`` of ``1`` (``docs/protocol.md`` section 3),
        taken under the device lock by
        :meth:`~groveyard.devices.base.DigitalOutputDevice.set_state`.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        await self.on()

    async def open_circuit(self) -> None:
        """Release the coil so the contacts stop conducting.

        One bridged ``digital_write`` of ``0`` (``docs/protocol.md`` section 3),
        taken under the device lock by
        :meth:`~groveyard.devices.base.DigitalOutputDevice.set_state`.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        await self.off()
