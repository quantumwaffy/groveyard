"""The connection object: lifecycle, port ownership and pin-mode cache.

:class:`Board` sits between the protocol layer and the drivers. It is the single
collaborator a driver talks to, which keeps drivers free of bus and encoding
concerns (and keeps the call graph flat: a driver never reaches through the board
into the transport).

Responsibilities:

* open and close the connection, and run the firmware-version handshake;
* hand out and validate ports, refusing to let two drivers share one socket;
* remember which pin mode each port is already configured for, so repeated reads
  do not re-send ``pin_mode``;
* expose the bridged operations in terms of :class:`~groveyard.ports.Port` values,
  and lend the raw bus session to native-I2C drivers such as the RGB LCD.

The board holds exactly one lock, and it is the *outermost* one: a lifecycle lock
serialising :meth:`Board.connect` and :meth:`Board.disconnect`. The full order is
**lifecycle → device → bus**, and it is never taken in the other direction —
`disconnect` calls into devices, no device ever calls back into the lifecycle.
Ordinary traffic takes no board lock at all: bus atomicity belongs to the
transport and device-state atomicity belongs to each driver.

The pin-mode cache is deliberately unlocked. Every entry is owned by exactly one
device (see :meth:`Board.attach`), and is only read or written while that device
holds its own lock, so there is no second writer to race with. That invariant
holds for the drivers; it can be broken by calling the bridged operations below
directly on the board while a driver owns the same port — see the warning on
:meth:`Board.set_pin_mode`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final, Self

from groveyard.errors import GroveyardError, NotConnectedError, PortInUseError
from groveyard.ports import AnalogPort, DigitalPort, PinMode, PortKind
from groveyard.protocol.bridge import BridgeProtocol
from groveyard.protocol.commands import DhtVariant
from groveyard.transport.i2c import DEFAULT_BUS_NUMBER, SMBusTransport

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from groveyard.devices.base import Device
    from groveyard.ports import Port
    from groveyard.protocol.bridge import FirmwareVersion
    from groveyard.transport.base import BusSession, RetryPolicy, Transport

_LOGGER: Final = logging.getLogger(__name__)

type PortKey = tuple[PortKind, int]
"""Identity of a socket: its family plus its number, so ``D2`` and ``A2`` differ."""


class Board:
    """An open connection to a GrovePi+ HAT.

    The board owns the connection, not the devices: drivers are constructed
    against a board and register themselves with it. That keeps the board closed
    for modification — adding a new module means adding a
    :class:`~groveyard.devices.base.Device` subclass, never editing this class.

    Example:
        ```python
        async with Board.on_i2c() as board:
            led = Led(board, DigitalPort.D4)
            await led.on()
        ```
    """

    def __init__(self, transport: Transport, bridge: BridgeProtocol | None = None) -> None:
        """Wire the board to its collaborators without opening the connection.

        Args:
            transport: Bus abstraction to use. Inject
                :class:`~groveyard.transport.fake.FakeTransport` in tests and
                :class:`~groveyard.transport.i2c.SMBusTransport` on a Pi.
            bridge: Encoder for the firmware command set. Defaults to a
                :class:`~groveyard.protocol.bridge.BridgeProtocol` bound to
                ``transport``; inject one to change addressing or retry policy.
        """
        self._transport = transport
        self._bridge = bridge or BridgeProtocol(transport)
        self._devices: dict[PortKey, Device] = {}
        self._pin_modes: dict[PortKey, PinMode] = {}
        self._firmware_version: FirmwareVersion | None = None
        self._connected = False
        self._lifecycle_lock = asyncio.Lock()

    @classmethod
    def on_i2c(cls, bus_number: int = DEFAULT_BUS_NUMBER, retry_policy: RetryPolicy | None = None) -> Self:
        """Build a board that talks to real hardware over ``/dev/i2c-<n>``.

        Args:
            bus_number: I2C bus number. Bus 1 on every modern Raspberry Pi.
            retry_policy: How transient bus faults are retried.

        Returns:
            A board that is not connected yet.
        """
        return cls(SMBusTransport(bus_number=bus_number, retry_policy=retry_policy))

    @property
    def is_connected(self) -> bool:
        """Whether :meth:`connect` has completed and :meth:`disconnect` has not run."""
        return self._connected

    @property
    def firmware_version(self) -> FirmwareVersion:
        """Version reported by the board during the connect handshake.

        Raises:
            NotConnectedError: If the handshake has not run yet.
        """
        if self._firmware_version is None:
            msg = "firmware version is only known after connect()"
            raise NotConnectedError(msg)
        return self._firmware_version

    async def connect(self) -> Self:
        """Open the bus and perform the firmware-version handshake.

        Idempotent, and safe to call from several tasks at once: the lifecycle
        lock makes the check-and-open one step, so two callers cannot both open a
        handle or both run the handshake.

        Returns:
            The board itself, so it can be used fluently.

        Raises:
            DeviceNotReadyError: If the board never answered the handshake.
            ProtocolError: If the handshake reply was malformed.
            TransportError: If the bus could not be opened or used.
        """
        async with self._lifecycle_lock:
            if self._connected:
                return self
            await self._transport.open()
            try:
                self._firmware_version = await self._bridge.firmware_version()
            except GroveyardError:
                await self._transport.close()
                raise
            self._connected = True
            _LOGGER.debug("connected to GrovePi+ firmware %s", self._firmware_version)
            return self

    async def disconnect(self) -> None:
        """Shut every attached device down safely and close the bus.

        Devices are closed first and while the connection is still usable, so
        actuators can drive themselves back to *off*. A device that fails to shut
        down is logged and skipped: one broken module must not keep the bus open.
        Idempotent.

        Shutting down is a cleanup path, so the whole sweep runs inside a shield:
        a Ctrl-C or a collapsing :class:`asyncio.TaskGroup` cannot interrupt it
        half-way and leave actuators energised with the bus descriptor still open.
        The sweep is awaited to completion first, and only then is the
        cancellation re-raised, so when this method returns — or raises — the
        board really is shut down.

        Raises:
            asyncio.CancelledError: If the caller was cancelled during the sweep.
                Every device has still been shut down and the bus is closed.
        """
        async with self._lifecycle_lock:
            shutdown = asyncio.ensure_future(self._shut_everything_down())
            try:
                await asyncio.shield(shutdown)
            except asyncio.CancelledError:
                await shutdown
                raise

    async def _shut_everything_down(self) -> None:
        """Close every device, then the bus. Runs under the lifecycle lock.

        A device that fails to shut down is logged and skipped, because one broken
        module must not keep the bus open or strand the modules after it.
        """
        try:
            if self._connected:
                for device in list(self._devices.values()):
                    try:
                        await device.close()
                    except GroveyardError:
                        _LOGGER.warning(
                            "device on %s failed to shut down cleanly",
                            device.describe(),
                            exc_info=True,
                        )
        finally:
            self._connected = False
            self._pin_modes.clear()
            await self._transport.close()

    async def __aenter__(self) -> Self:
        """Connect on entering an ``async with`` block.

        Returns:
            The connected board.
        """
        return await self.connect()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Disconnect on leaving an ``async with`` block, including on error.

        Args:
            exc_type: Type of the exception that is propagating, if any.
            exc: The exception that is propagating, if any.
            traceback: Traceback of that exception, if any.
        """
        await self.disconnect()

    def attach(self, device: Device, port: Port | None = None) -> None:
        """Claim a socket for a device.

        Args:
            device: The driver claiming the socket.
            port: The socket being claimed, or ``None`` for the shared I2C port.

        Raises:
            PortInUseError: If another live device already holds that socket.
        """
        key = self._key(port)
        owner = self._devices.get(key)
        if owner is not None and owner is not device:
            msg = f"{self._describe_key(key)} is already used by {type(owner).__name__}"
            raise PortInUseError(msg)
        self._devices[key] = device

    def detach(self, device: Device, port: Port | None = None) -> None:
        """Release a socket previously claimed by a device.

        Releasing a socket the device does not own is a no-op, so closing twice is
        harmless.

        Args:
            device: The driver releasing the socket.
            port: The socket being released, or ``None`` for the shared I2C port.
        """
        key = self._key(port)
        if self._devices.get(key) is device:
            del self._devices[key]
            self._pin_modes.pop(key, None)

    async def ensure_pin_mode(self, port: Port, mode: PinMode) -> None:
        """Configure a port's direction unless it is already configured that way.

        Callers must hold their device lock, which is what makes the cache
        race-free: a port belongs to exactly one device.

        Args:
            port: Socket to configure.
            mode: Direction the driver needs.

        Raises:
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        key = self._key(port)
        if self._pin_modes.get(key) is mode:
            return
        await self.set_pin_mode(port, mode)

    async def set_pin_mode(self, port: Port, mode: PinMode) -> None:
        """Configure a port's direction unconditionally and remember it.

        Warning:
            This and the bridged operations below are the plumbing the drivers
            are built on. They take **no device lock**, so calling them on a port
            that a driver already owns races that driver's cached state — drive
            the device through its own class instead. They are public because a
            module this library does not ship yet still has to be reachable.

        Args:
            port: Socket to configure.
            mode: Direction to configure.

        Raises:
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        self._require_connected()
        await self._bridge.set_pin_mode(int(port), mode)
        self._pin_modes[self._key(port)] = mode

    async def digital_read(self, port: DigitalPort) -> int:
        """Read the logic level of a digital socket.

        Args:
            port: Digital socket to read.

        Returns:
            ``0`` for low, ``1`` for high.

        Raises:
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        self._require_connected()
        return await self._bridge.digital_read(int(port))

    async def digital_write(self, port: DigitalPort, value: int) -> None:
        """Drive a digital socket high or low.

        Args:
            port: Digital socket to drive.
            value: ``0`` for low, ``1`` for high.

        Raises:
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        self._require_connected()
        await self._bridge.digital_write(int(port), value)

    async def analog_read(self, port: AnalogPort) -> int:
        """Read the ADC value of an analog socket.

        Args:
            port: Analog socket to read.

        Returns:
            Raw counts in ``0..1023``.

        Raises:
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        self._require_connected()
        return await self._bridge.analog_read(int(port))

    async def analog_write(self, port: Port, value: int) -> None:
        """Set the PWM duty cycle of a socket.

        Args:
            port: Socket to drive. Digital sockets that the firmware can PWM are
                the usual target.
            value: Duty cycle in ``0..255``.

        Raises:
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        self._require_connected()
        await self._bridge.analog_write(int(port), value)

    async def ultrasonic_read(self, port: DigitalPort) -> int:
        """Trigger an ultrasonic ping and read the distance it measured.

        Args:
            port: Digital socket the ranger is plugged into.

        Returns:
            Distance in centimetres, as reported by the firmware.

        Raises:
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        self._require_connected()
        return await self._bridge.ultrasonic_read(int(port))

    async def dht_read(self, port: DigitalPort, variant: DhtVariant = DhtVariant.DHT11) -> tuple[float, float]:
        """Read temperature and humidity from a DHT sensor.

        Args:
            port: Digital socket the sensor is plugged into.
            variant: Which DHT variant is connected.

        Returns:
            A ``(temperature_celsius, humidity_percent)`` pair.

        Raises:
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If every attempt produced an implausible reading.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        self._require_connected()
        return await self._bridge.dht_read(int(port), variant)

    async def wait(self, seconds: float) -> None:
        """Wait for a device that needs time but does not need the bus.

        Used by drivers whose controller needs a settling period — the RGB LCD
        after a clear, for instance. Keeping such a delay out of
        :meth:`bus_session` is what stops one slow display from stalling every
        other device for 50 ms.

        Args:
            seconds: How long to wait. Never blocks the event loop.
        """
        await self._transport.wait(seconds)

    def bus_session(self) -> AbstractAsyncContextManager[BusSession]:
        """Borrow the bus for one transaction, for native-I2C drivers.

        Modules such as the RGB LCD do not go through the bridge, but they do
        share the wires, so they must use the same lock. This hands out the
        transport's session unchanged.

        Warning:
            The session **is** the bus lock. Never call a device method while one
            is open: the device would take its own lock and then wait forever for
            the bus lock this task is already holding. Keep the block to raw
            ``session`` calls, and take the delays that do not need the bus with
            :meth:`wait` instead.

        Returns:
            An async context manager yielding a
            :class:`~groveyard.transport.base.BusSession`.

        Raises:
            NotConnectedError: If the board is not connected.
        """
        self._require_connected()
        return self._transport.session()

    def _require_connected(self) -> None:
        """Guard operations that need an open connection.

        Raises:
            NotConnectedError: If the board is not connected.
        """
        if not self._connected:
            msg = "board is not connected; call connect() or use it as an async context manager"
            raise NotConnectedError(msg)

    def _key(self, port: Port | None) -> PortKey:
        """Build the registry key identifying a socket.

        Args:
            port: Socket to identify, or ``None`` for the shared I2C port.

        Returns:
            A ``(kind, number)`` pair, distinguishing ``D2`` from ``A2``.

        Raises:
            TypeError: If ``port`` is not a known port type.
        """
        if port is None:
            return (PortKind.I2C, 0)
        if isinstance(port, DigitalPort | AnalogPort):
            return (port.kind, int(port))
        msg = f"expected a DigitalPort or an AnalogPort, got {type(port).__name__}"
        raise TypeError(msg)

    def _describe_key(self, key: PortKey) -> str:
        """Render a registry key for error messages.

        Args:
            key: The ``(kind, number)`` pair to describe.

        Returns:
            A human-readable socket name such as ``"digital port 4"``.
        """
        kind, number = key
        if kind is PortKind.I2C:
            return "the I2C port"
        return f"{kind.value} port {number}"
