"""Base classes every device driver builds on.

A driver models one physical module. It contributes three things and nothing
else: the *intent* of an operation, the small amount of *state* that operation
depends on, and the *per-device lock* that keeps that state consistent. Bytes
belong to :mod:`groveyard.protocol`, the bus belongs to
:mod:`groveyard.transport`, and port bookkeeping belongs to
:class:`~groveyard.board.Board`.

Locking discipline
------------------

:class:`asyncio.Lock` is **not reentrant**, so this module follows one rule
throughout, and every driver must follow it too:

* public methods acquire ``self._lock`` and immediately delegate to a private
  ``*_locked`` helper;
* ``*_locked`` helpers assume the lock is held and never take it again, so they
  are free to call each other;
* the lock is released automatically on cancellation, because it is always taken
  with ``async with``.

The lock is taken *before* any bus traffic, so the library-wide order — device
lock, then bus lock — holds by construction. Nothing here calls back into another
device while a bus session is open.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self

from groveyard.errors import DeviceClosedError, GroveyardError
from groveyard.ports import AnalogPort, DigitalPort, PinMode
from groveyard.protocol.commands import ADC_MAX_COUNTS, DIGITAL_HIGH, DIGITAL_LOW

if TYPE_CHECKING:
    from types import TracebackType

    from groveyard.board import Board
    from groveyard.ports import Port


class Device(ABC):
    """A module attached to a board, with its own lock and lifecycle.

    Subclasses add the operations their hardware supports. They inherit the
    lock, the closed-state guard and the async-context-manager protocol, so a
    driver body stays about the device and nothing else.
    """

    def __init__(self, board: Board) -> None:
        """Bind the driver to a board.

        Args:
            board: The connection this device operates on. Injected so drivers
                depend on the board abstraction rather than building transports.
        """
        self._board = board
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """Whether :meth:`close` has already run."""
        return self._closed

    @abstractmethod
    def describe(self) -> str:
        """Return a short human-readable identity, used in logs and errors.

        Every driver names itself, so a warning about a device that failed to
        shut down says which socket to go and look at.

        Returns:
            For example ``"Led on D4"``.
        """

    async def close(self) -> None:
        """Shut the device down safely and release its port.

        Actuators drive themselves back to *off* here, which is why closing runs
        while the connection is still open. Idempotent, and safe to call from a
        ``finally`` block.

        The device is marked closed only once the shutdown has actually run. A
        cancelled shutdown therefore leaves the device **open**, so the caller can
        try again — marking it closed would strand an energised actuator that
        every later ``close()`` skips over.

        Raises:
            GroveyardError: If the safe-state write failed. The device is still
                marked closed and its port released, because a device whose
                hardware cannot be reached is not usable either.
            asyncio.CancelledError: If the shutdown was cancelled. The device
                stays open and can be closed again.
        """
        async with self._lock:
            if self._closed:
                return
            try:
                await self._shutdown_locked()
            except asyncio.CancelledError:
                raise
            except GroveyardError:
                self._retire()
                raise
            else:
                self._retire()

    def _retire(self) -> None:
        """Mark the device closed and give its port back. Called with the lock held."""
        self._closed = True
        self._release()

    async def __aenter__(self) -> Self:
        """Return the device on entering an ``async with`` block.

        Returns:
            The device itself.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the device on leaving an ``async with`` block, including on error.

        Args:
            exc_type: Type of the exception that is propagating, if any.
            exc: The exception that is propagating, if any.
            traceback: Traceback of that exception, if any.
        """
        await self.close()

    async def _shutdown_locked(self) -> None:  # noqa: B027 - optional hook: sensors have no safe state to restore
        """Bring the hardware to its safe state. Called with the lock held.

        Sensors have nothing to do; actuators override this to switch off.
        """

    def _release(self) -> None:  # noqa: B027 - optional hook: only port-bound devices have something to release
        """Give the device's port back to the board. Called with the lock held."""

    def _require_open(self) -> None:
        """Guard operations that need a live device.

        Raises:
            DeviceClosedError: If the device has been closed.
        """
        if self._closed:
            msg = f"{self.describe()} is closed"
            raise DeviceClosedError(msg)


class PortDevice[P: Port](Device):
    """A device that occupies one Grove socket.

    Claiming the socket at construction time is deliberate: it turns "two drivers
    on one port" — which would corrupt the shared pin-mode cache — into an
    immediate, obvious error instead of a race.
    """

    def __init__(self, board: Board, port: P) -> None:
        """Claim a socket for this device.

        Args:
            board: The connection this device operates on.
            port: The socket the module is plugged into.

        Raises:
            PortInUseError: If another live device already holds that socket.
        """
        super().__init__(board)
        self._port = port
        board.attach(self, port)

    @property
    def port(self) -> P:
        """The socket this device is plugged into."""
        return self._port

    def describe(self) -> str:
        """Return the driver name together with its socket.

        Returns:
            For example ``"Button on D3"``.
        """
        return f"{type(self).__name__} on {self._port.name}"

    def _release(self) -> None:
        """Return the socket to the board so another driver may claim it."""
        self._board.detach(self, self._port)


class I2CDevice(Device):
    """A module with its own controller on the shared I2C bus.

    It occupies no Grove socket, so it claims the board's single I2C port
    instead — which still means two drivers cannot fight over one panel. Such a
    device talks through :meth:`~groveyard.board.Board.bus_session` and owns its
    register constants; the bridge protocol layer knows nothing about it
    (``docs/protocol.md`` section 4).
    """

    def __init__(self, board: Board) -> None:
        """Claim the shared I2C port for this device.

        Args:
            board: The connection this device operates on.

        Raises:
            PortInUseError: If another live device already holds the I2C port.
        """
        super().__init__(board)
        board.attach(self)

    def describe(self) -> str:
        """Return the driver name and the port family it occupies.

        Returns:
            For example ``"RgbLcd on the I2C port"``.
        """
        return f"{type(self).__name__} on the I2C port"

    def _release(self) -> None:
        """Return the shared I2C port to the board so another driver may claim it."""
        self._board.detach(self)


class BridgedDevice[P: Port](PortDevice[P]):
    """A device the board firmware drives on our behalf.

    Adds the one piece of setup every bridged module needs: configuring the pin
    direction once and not again. The board keeps the cache; the device's lock is
    what makes reading and updating it safe.
    """

    async def _ensure_mode_locked(self, mode: PinMode) -> None:
        """Configure the port's direction if it is not already set. Lock held.

        Args:
            mode: Direction this operation needs.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        self._require_open()
        await self._board.ensure_pin_mode(self._port, mode)


class DigitalInputDevice(BridgedDevice[DigitalPort]):
    """A module that reports a single on/off level, such as a button.

    The port is configured as an input on first use and stays that way.
    """

    async def read_value(self) -> int:
        """Read the raw logic level of the port.

        Returns:
            ``0`` when the signal is low, ``1`` when it is high.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_value_locked()

    async def is_high(self) -> bool:
        """Report whether the signal is currently high.

        Returns:
            ``True`` if the port reads ``1``.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        return await self.read_value() == DIGITAL_HIGH

    async def _read_value_locked(self) -> int:
        """Configure the port as an input and read it. Lock held.

        Returns:
            ``0`` or ``1``.
        """
        self._require_open()
        await self._ensure_mode_locked(PinMode.INPUT)
        return await self._board.digital_read(self._port)


class DigitalOutputDevice(BridgedDevice[DigitalPort]):
    """A module that is simply switched on or off, such as a relay or a buzzer.

    The driver caches the level it last commanded so that :attr:`is_on` and
    :meth:`toggle` do not need a bus round trip, and so that :meth:`close` knows
    whether it still has to switch the hardware off.
    """

    def __init__(self, board: Board, port: DigitalPort) -> None:
        """Claim the socket and assume the output is off.

        The assumption is made true by the first write, and by :meth:`close`,
        which always leaves the port low.

        Args:
            board: The connection this device operates on.
            port: The socket the module is plugged into.

        Raises:
            PortInUseError: If another live device already holds that socket.
        """
        super().__init__(board, port)
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """The level this driver last commanded, without touching the bus."""
        return self._is_on

    async def on(self) -> None:
        """Switch the output on.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        await self.set_state(state=True)

    async def off(self) -> None:
        """Switch the output off.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        await self.set_state(state=False)

    async def set_state(self, *, state: bool) -> None:
        """Drive the output to an explicit level.

        Args:
            state: ``True`` for on, ``False`` for off.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            await self._set_state_locked(state=state)

    async def toggle(self) -> bool:
        """Flip the output and report the new level.

        Reading the cached level and writing the new one happen under one lock, so
        two tasks toggling the same device cannot both observe the same "before"
        value.

        Returns:
            The level the output now holds.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            await self._set_state_locked(state=not self._is_on)
            return self._is_on

    async def _set_state_locked(self, *, state: bool) -> None:
        """Configure the port as an output and drive it. Lock held.

        The cached level is updated only after the write succeeds, so a failed
        write never leaves the driver claiming a state the hardware is not in.

        Args:
            state: ``True`` for on, ``False`` for off.
        """
        self._require_open()
        await self._ensure_mode_locked(PinMode.OUTPUT)
        await self._board.digital_write(self._port, DIGITAL_HIGH if state else DIGITAL_LOW)
        self._is_on = state

    async def _shutdown_locked(self) -> None:
        """Drive the output low so the module cannot be left energised. Lock held."""
        await self._ensure_mode_locked(PinMode.OUTPUT)
        await self._board.digital_write(self._port, DIGITAL_LOW)
        self._is_on = False


class AnalogInputDevice(BridgedDevice[AnalogPort]):
    """A module read through the board's 10-bit ADC.

    Raw counts are always available; unit conversions belong to the concrete
    driver and are layered on top of :meth:`read_raw`, never in place of it.
    """

    async def read_raw(self) -> int:
        """Read the ADC value of the port.

        Returns:
            Raw counts in ``0..1023``, where ``1023`` is full scale (5 V).

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            return await self._read_raw_locked()

    async def read_ratio(self) -> float:
        """Read the ADC value normalised to full scale.

        Returns:
            A value in ``0.0..1.0``.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        return await self.read_raw() / ADC_MAX_COUNTS

    async def _read_raw_locked(self) -> int:
        """Configure the port as an input and read the ADC. Lock held.

        Returns:
            Raw counts in ``0..1023``.
        """
        self._require_open()
        await self._ensure_mode_locked(PinMode.INPUT)
        return await self._board.analog_read(self._port)
