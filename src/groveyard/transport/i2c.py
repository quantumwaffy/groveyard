"""Real-hardware transport backed by ``smbus2`` on a Raspberry Pi.

``smbus2`` is imported lazily, inside :meth:`SMBusTransport.open`, for two
reasons: the package is an optional extra (``groveyard[hardware]``), and the test
suite must never import it. Everything above this module talks to the abstract
:class:`~groveyard.transport.base.Transport`, so development and CI run entirely
against the in-memory fake.

All ``smbus2`` calls are blocking C-level I/O and therefore run in a worker thread
via :func:`asyncio.to_thread`; delays use :func:`asyncio.sleep`. The event loop is
never blocked.

One physical bus, one transport
--------------------------------

Every safety guarantee in this library — the bus lock, the port registry — is
scoped to *one* :class:`~groveyard.transport.base.Transport` instance. Nothing
stops a caller from constructing two independent :class:`SMBusTransport`
objects with the same ``bus_number``: the OS happily opens
``/dev/i2c-<n>`` twice, and the two instances would then drive the same
physical wires with two locks that know nothing about each other — every
atomicity guarantee in ``docs/architecture/concurrency.md`` silently stops
holding between them. :class:`SMBusTransport` guards against this *within a
process* by refusing to open a ``bus_number`` that another live
:class:`SMBusTransport` already has open (see :data:`SMBusTransport._open_bus_numbers`).
It cannot guard against two separate *processes* opening the same device
node — that needs OS-level file locking, which this library does not
attempt. Build one :class:`~groveyard.board.Board` per physical bus per
process and share it between every driver that needs it.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, ClassVar, Final, Protocol

from groveyard.errors import TransportError
from groveyard.transport.base import BusSession, RetryPolicy, Transport

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DEFAULT_BUS_NUMBER: Final[int] = 1
"""``/dev/i2c-1`` is the user-accessible bus on every modern Raspberry Pi."""


class SMBusHandle(Protocol):
    """Structural type for the subset of ``smbus2.SMBus`` this transport uses.

    Declaring it structurally keeps the hardware dependency out of the type graph:
    nothing in the library imports ``smbus2`` to be type-checked.
    """

    def i2c_rdwr(self, *messages: object) -> None:
        """Run one or more raw I2C messages as a single ioctl."""

    def write_byte_data(self, address: int, register: int, value: int) -> None:
        """Write one byte to a device register (SMBus protocol)."""

    def close(self) -> None:
        """Release the underlying file descriptor."""


class I2CMessageFactory(Protocol):
    """Structural type for ``smbus2.i2c_msg``, the raw-message builder."""

    def read(self, address: int, length: int) -> Iterable[int]:
        """Build a read message of ``length`` bytes from ``address``."""

    def write(self, address: int, data: bytes) -> object:
        """Build a write message carrying ``data`` to ``address``."""


class SMBusSession(BusSession):
    """One locked transaction against a real I2C bus.

    Instances are created by :class:`SMBusTransport` while the bus lock is held
    and are discarded when the transaction ends. Each raw operation is retried
    according to the transport's :class:`~groveyard.transport.base.RetryPolicy`;
    because the bus lock is held throughout, a retry cannot be interleaved with
    another task's traffic.
    """

    def __init__(self, bus: SMBusHandle, messages: I2CMessageFactory, retry_policy: RetryPolicy) -> None:
        """Bind the session to an open bus handle.

        Args:
            bus: Open ``smbus2.SMBus`` handle.
            messages: The ``smbus2.i2c_msg`` factory used to build raw messages.
            retry_policy: How often to retry a transient bus fault.
        """
        self._bus = bus
        self._messages = messages
        self._retry_policy = retry_policy

    async def write(self, address: int, payload: bytes) -> None:
        """Write raw bytes as a single I2C write transaction.

        Args:
            address: 7-bit I2C address of the target device.
            payload: Bytes to place on the bus, exactly as given.

        Raises:
            TransportError: If the bus rejected the write on every attempt.
        """
        message = self._messages.write(address, payload)
        await self._run(f"write {len(payload)} byte(s) to {address:#04x}", self._bus.i2c_rdwr, message)

    async def read(self, address: int, count: int) -> bytes:
        """Read raw bytes as a standalone I2C read transaction.

        Args:
            address: 7-bit I2C address of the target device.
            count: Number of bytes to read.

        Returns:
            Exactly ``count`` bytes.

        Raises:
            TransportError: If the bus rejected the read on every attempt, or the
                device returned fewer bytes than requested.
        """
        message = self._messages.read(address, count)
        await self._run(f"read {count} byte(s) from {address:#04x}", self._bus.i2c_rdwr, message)
        data = bytes(bytearray(message))
        if len(data) != count:
            msg = f"short read from {address:#04x}: expected {count} byte(s), got {len(data)}"
            raise TransportError(msg)
        return data

    async def write_register(self, address: int, register: int, value: int) -> None:
        """Write one byte to a device register.

        Args:
            address: 7-bit I2C address of the target device.
            register: Register (command) byte.
            value: Byte to store in that register.

        Raises:
            TransportError: If the bus rejected the write on every attempt.
        """
        await self._run(
            f"write {value:#04x} to register {register:#04x} of {address:#04x}",
            self._bus.write_byte_data,
            address,
            register,
            value,
        )

    async def settle(self, seconds: float) -> None:
        """Wait for the device to service the command, without blocking the loop.

        Args:
            seconds: How long to wait.
        """
        await asyncio.sleep(seconds)

    async def _run(self, description: str, operation: Callable[..., object], *args: object) -> None:
        """Run one blocking bus call in a worker thread, with bounded retries.

        Args:
            description: Human-readable operation summary, used in error messages.
            operation: The blocking ``smbus2`` callable to invoke.
            *args: Positional arguments for ``operation``.

        Raises:
            TransportError: If every attempt raised ``OSError``.
        """
        last_error: OSError | None = None
        for attempt in range(1, self._retry_policy.attempts + 1):
            delay = self._retry_policy.delay_before(attempt)
            if delay:
                await asyncio.sleep(delay)
            try:
                # Shielded on purpose: a cancelled `to_thread` returns immediately
                # while the worker thread keeps driving the ioctl. Abandoning it
                # would release the bus lock with a transfer still on the wire,
                # and the next task's reply would collide with ours. The shielded
                # region is bounded by the ioctl, not by user-controlled time.
                await asyncio.shield(asyncio.to_thread(operation, *args))
            except OSError as error:
                last_error = error
            else:
                return
        msg = f"I2C bus failed to {description} after {self._retry_policy.attempts} attempt(s)"
        raise TransportError(msg) from last_error


class SMBusTransport(Transport):
    """Transport that drives a real I2C bus through ``smbus2``.

    Example:
        ```python
        transport = SMBusTransport(bus_number=1)
        async with Board(transport) as board:
            ...
        ```
    """

    _open_bus_numbers: ClassVar[set[int]] = set()
    """Bus numbers a live :class:`SMBusTransport` currently has open, process-wide.

    Shared across every instance on purpose: it is what lets a second
    :class:`SMBusTransport` on the same ``bus_number`` be rejected instead of
    silently opening a second, uncoordinated file descriptor onto wires a
    first instance is already serialising traffic on.
    """

    _registry_lock: ClassVar[threading.Lock] = threading.Lock()
    """Guards :data:`_open_bus_numbers`.

    A :class:`threading.Lock`, deliberately, not an :class:`asyncio.Lock`. The
    registry's whole job is to catch a *second* transport that shares no other
    lock with the first — and that second transport may well be driven by a
    second event loop in a second thread. An ``asyncio.Lock`` cannot serialise
    that: its uncontended path is a plain ``if not self._locked: self._locked
    = True``, which is neither atomic across threads nor loop-aware, and its
    contended path parks a future on whichever loop got there first, so a
    release from the other thread never wakes it — the two threads deadlock
    instead of one of them being rejected.

    Holding a thread lock from async code is safe here because the critical
    section is a set lookup and a set insert: no awaits, no I/O, microseconds.
    """

    def __init__(self, bus_number: int = DEFAULT_BUS_NUMBER, retry_policy: RetryPolicy | None = None) -> None:
        """Configure the transport without touching the hardware yet.

        Args:
            bus_number: I2C bus to open, i.e. ``/dev/i2c-<bus_number>``. Defaults
                to bus 1, the user-accessible bus on modern Raspberry Pis.
            retry_policy: How transient bus faults are retried. Defaults to
                :class:`~groveyard.transport.base.RetryPolicy`'s own defaults.
        """
        super().__init__()
        self._bus_number = bus_number
        self._retry_policy = retry_policy or RetryPolicy()
        self._bus: SMBusHandle | None = None
        self._messages: I2CMessageFactory | None = None

    @property
    def bus_number(self) -> int:
        """The I2C bus number this transport opens."""
        return self._bus_number

    @property
    def is_open(self) -> bool:
        """Whether the bus handle is currently open."""
        return self._bus is not None

    async def _open(self) -> None:
        """Open ``/dev/i2c-<bus_number>``. Called with the bus lock held.

        Registers ``bus_number`` in :data:`_open_bus_numbers` *before* touching
        ``smbus2``, and releases it again if anything below fails — including
        cancellation — so a bus number can never get stuck "reserved" by an
        open attempt that never actually succeeded.

        Idempotent: opening an already-open transport does nothing.

        Raises:
            TransportError: If another live :class:`SMBusTransport` in this
                process already has ``bus_number`` open, ``smbus2`` is not
                installed, or the bus cannot be opened (missing device node,
                no permission, I2C disabled).
        """
        if self._bus is not None:
            return
        self._reserve_bus_number()
        opened = False
        try:
            try:
                # Imported here, not at module scope: smbus2 is an optional extra and
                # must never be imported by the test path.
                import smbus2  # ty: ignore[unresolved-import]
            except ImportError as error:  # pragma: no cover - depends on the host
                msg = "smbus2 is required for real hardware access; install groveyard[hardware]"
                raise TransportError(msg) from error
            try:
                bus = await asyncio.to_thread(smbus2.SMBus, self._bus_number)
            except OSError as error:  # pragma: no cover - depends on the host
                msg = f"cannot open I2C bus {self._bus_number}; is I2C enabled and is the user in the i2c group?"
                raise TransportError(msg) from error
            self._bus = bus
            self._messages = smbus2.i2c_msg
            opened = True
        finally:
            if not opened:
                self._release_bus_number()

    async def _close(self) -> None:
        """Close the bus handle. Called with the bus lock held.

        Holding the lock is what stops the descriptor being pulled out from
        under a transaction that another task is still running. The bus number
        is released from :data:`_open_bus_numbers` even if closing the real
        handle raises, so a failed close cannot permanently strand it as
        "reserved" for the rest of the process.

        Idempotent: closing an already-closed transport does nothing.
        """
        bus, self._bus = self._bus, None
        self._messages = None
        if bus is not None:
            try:
                await asyncio.to_thread(bus.close)
            finally:
                self._release_bus_number()

    def _reserve_bus_number(self) -> None:
        """Claim :attr:`bus_number` for this instance, process-wide.

        Synchronous on purpose: the check and the insert must be one
        indivisible step, and there is nothing to await between them. Being
        sync is also what lets the matching release run inside a ``finally``
        without introducing a cancellation point in a cleanup path.

        Raises:
            TransportError: If another live :class:`SMBusTransport` in this
                process — on any thread, in any event loop — already has this
                bus number open.
        """
        with SMBusTransport._registry_lock:
            if self._bus_number in SMBusTransport._open_bus_numbers:
                msg = (
                    f"I2C bus {self._bus_number} is already open by another SMBusTransport "
                    "in this process. Two independent transports on the same physical bus "
                    "would each enforce their own, uncoordinated bus lock, silently defeating "
                    "the atomicity this library depends on — construct one Board per physical "
                    "bus and share it between every driver that needs it, instead of building "
                    "a second one."
                )
                raise TransportError(msg)
            SMBusTransport._open_bus_numbers.add(self._bus_number)

    def _release_bus_number(self) -> None:
        """Give :attr:`bus_number` back so another :class:`SMBusTransport` may open it."""
        with SMBusTransport._registry_lock:
            SMBusTransport._open_bus_numbers.discard(self._bus_number)

    def _create_session(self) -> BusSession:
        """Build a session bound to the open bus handle.

        Returns:
            An :class:`SMBusSession` for exactly one transaction.

        Raises:
            TransportError: If the transport was closed concurrently.
        """
        if self._bus is None or self._messages is None:  # pragma: no cover - guarded by Transport.session
            msg = "transport is not open"
            raise TransportError(msg)
        return SMBusSession(self._bus, self._messages, self._retry_policy)
