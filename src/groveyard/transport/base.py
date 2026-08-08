"""Transport abstractions: the bus handle and the one bus-wide lock.

This is the bottom layer. It knows about bytes and addresses and nothing else —
no commands, no devices. Its single responsibility is to move bytes over the I2C
bus *atomically*, because every bridged operation is a ``write → sleep → read``
sequence that must not be interleaved with any other traffic
(``docs/protocol.md`` section 2).

Atomicity is expressed as a **session**: callers ask the transport for a session,
and the transport hands one out only while holding the bus lock::

    async with transport.session() as bus:
        await bus.write(0x04, frame)
        await bus.settle(0.002)
        reply = await bus.read(0x04, 3)

Because native-I2C modules share the same physical wires, they go through the
same session mechanism with a different address, and are therefore serialized
against bridged traffic as well.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from groveyard.errors import TransportError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DEFAULT_RETRY_ATTEMPTS: Final[int] = 3
"""How many times a raw bus operation is tried before giving up."""

DEFAULT_RETRY_BACKOFF_SECONDS: Final[float] = 0.005
"""Base delay between retries of a failed raw bus operation."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How a transport reacts to transient bus faults.

    A shared I2C bus occasionally returns ``OSError`` for reasons that disappear
    on the next attempt (arbitration, a busy slave). Retrying a *raw* operation is
    safe because the bus lock is held for the whole surrounding transaction, so no
    other task can slip in between attempts.

    Attributes:
        attempts: Total number of tries, including the first one. Must be >= 1.
        backoff_seconds: Delay before retry ``n``, scaled linearly by ``n``.
    """

    attempts: int = DEFAULT_RETRY_ATTEMPTS
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS

    def __post_init__(self) -> None:
        """Validate the policy.

        Raises:
            ValueError: If ``attempts`` is below 1 or ``backoff_seconds`` is negative.
        """
        if self.attempts < 1:
            msg = f"attempts must be >= 1, got {self.attempts}"
            raise ValueError(msg)
        if self.backoff_seconds < 0:
            msg = f"backoff_seconds must be >= 0, got {self.backoff_seconds}"
            raise ValueError(msg)

    def delay_before(self, attempt: int) -> float:
        """Return the delay to wait before the given retry.

        Args:
            attempt: 1-based index of the attempt that is about to be made.

        Returns:
            Delay in seconds; ``0.0`` before the very first attempt.
        """
        return self.backoff_seconds * (attempt - 1)


class BusSession(ABC):
    """Exclusive access to the I2C bus for the duration of one transaction.

    A session is handed out by :meth:`Transport.session` while the bus lock is
    held, and must not be used after the surrounding ``async with`` block exits.
    Implementations translate these calls into real I2C traffic or record them for
    tests.
    """

    @abstractmethod
    async def write(self, address: int, payload: bytes) -> None:
        """Write a raw byte string to a device.

        Args:
            address: 7-bit I2C address of the target device.
            payload: Bytes to place on the bus, exactly as given.

        Raises:
            TransportError: If the bus rejects the write.
        """

    @abstractmethod
    async def read(self, address: int, count: int) -> bytes:
        """Read a raw byte string from a device.

        This is a standalone read transaction, not a repeated-start read: the
        bridge firmware buffers its reply and returns it on the next read
        (``docs/protocol.md`` section 2).

        Args:
            address: 7-bit I2C address of the target device.
            count: Number of bytes to read.

        Returns:
            Exactly ``count`` bytes.

        Raises:
            TransportError: If the bus rejects the read or returns short data.
        """

    @abstractmethod
    async def write_register(self, address: int, register: int, value: int) -> None:
        """Write one byte to a device register (SMBus ``write_byte_data``).

        Used by native-I2C modules such as the RGB LCD, which address their
        controllers by register rather than through the bridge
        (``docs/protocol.md`` section 4).

        Args:
            address: 7-bit I2C address of the target device.
            register: Register (command) byte.
            value: Byte to store in that register.

        Raises:
            TransportError: If the bus rejects the write.
        """

    @abstractmethod
    async def settle(self, seconds: float) -> None:
        """Wait inside the transaction while the device services the command.

        The delay belongs to the session — and therefore stays inside the bus
        lock — because reading before the firmware is done yields the previous
        reply or a not-ready sentinel.

        Args:
            seconds: How long to wait. Implementations never block the event loop.
        """


class Transport(ABC):
    """Owns the bus handle and the single bus-wide lock.

    Subclasses implement the actual byte movement; this class owns the invariant
    that only one transaction touches the bus at a time. It is the *innermost*
    lock in the library: the documented order is **device lock → bus lock**, and
    nothing inside a session may call back into a device.
    """

    def __init__(self) -> None:
        """Create the transport and its bus lock, without opening the bus."""
        self._bus_lock = asyncio.Lock()

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Whether the underlying bus handle is currently usable."""

    async def open(self) -> None:
        """Acquire the underlying bus handle.

        Runs under the bus lock, so opening cannot race a transaction that is
        already in flight and two concurrent calls cannot both build a handle.
        Calling this on an already-open transport is a no-op.

        Raises:
            TransportError: If the bus cannot be opened.
        """
        async with self._bus_lock:
            await self._open()

    async def close(self) -> None:
        """Release the underlying bus handle.

        Runs under the bus lock, so the handle is never pulled out from under an
        in-flight transaction. Calling this on an already-closed transport is a
        no-op.
        """
        async with self._bus_lock:
            await self._close()

    @abstractmethod
    async def _open(self) -> None:
        """Build the bus handle. Called with the bus lock held.

        Raises:
            TransportError: If the bus cannot be opened.
        """

    @abstractmethod
    async def _close(self) -> None:
        """Release the bus handle. Called with the bus lock held."""

    @abstractmethod
    def _create_session(self) -> BusSession:
        """Build the session object handed to the caller of :meth:`session`.

        Called with the bus lock held, exactly once per transaction.

        Returns:
            A session bound to this transport's bus handle.
        """

    async def wait(self, seconds: float) -> None:
        """Wait for a device that needs time but does not need the bus.

        Some controllers need a settling period during which nothing may be sent
        *to them* — but the bus itself is free, and holding it would stall every
        other device. Such a delay therefore lives here rather than on
        :class:`BusSession`, whose :meth:`~BusSession.settle` is for waits that
        must stay inside a transaction.

        Args:
            seconds: How long to wait. Never blocks the event loop.
        """
        await asyncio.sleep(seconds)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[BusSession]:
        """Hold the bus lock for one complete transaction.

        Every bus exchange in the library goes through this method, which is what
        makes ``write → settle → read`` atomic with respect to all other traffic,
        bridged or native-I2C.

        The open check happens *after* the lock is acquired: a task that waited
        for the lock may have been overtaken by a disconnect, and handing it a
        session bound to a closed handle would surface as a confusing bus error.

        Yields:
            A :class:`BusSession` valid only inside the ``async with`` block.

        Raises:
            TransportError: If the transport is not open.
        """
        async with self._bus_lock:
            if not self.is_open:
                msg = "transport is not open; call open() (or use Board as a context manager) first"
                raise TransportError(msg)
            yield self._create_session()
