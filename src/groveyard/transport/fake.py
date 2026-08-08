"""In-memory transport used by tests and by users testing their own code.

The fake records every bus operation and returns replies that a test either
scripts explicitly or delegates to a :class:`BusResponder` (see
:mod:`groveyard.testing.firmware` for one that emulates the bridge firmware). It
imports nothing from the hardware stack, so the whole library can be exercised on
a laptop.

Two properties make the fake a good test double for concurrency work:

* every recorded event carries the id of the session it happened in, so a test
  can assert that transactions never interleave;
* :meth:`FakeSession.settle` records the requested delay instead of sleeping, so
  timing requirements are asserted rather than waited for, and tests stay fast and
  deterministic.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from groveyard.errors import TransportError
from groveyard.transport.base import BusSession, Transport

NO_SESSION: Final[int] = 0
"""Session id stamped on events that happened outside any transaction."""

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class BusWrite:
    """A raw write that was placed on the fake bus.

    Attributes:
        session_id: Id of the transaction this happened in.
        address: 7-bit I2C address that was addressed.
        payload: Bytes the caller wrote.
    """

    session_id: int
    address: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class BusRead:
    """A raw read that was served from the fake bus.

    Attributes:
        session_id: Id of the transaction this happened in.
        address: 7-bit I2C address that was addressed.
        data: Bytes handed back to the caller.
    """

    session_id: int
    address: int
    data: bytes


@dataclass(frozen=True, slots=True)
class BusRegisterWrite:
    """A single-byte register write (SMBus ``write_byte_data``).

    Attributes:
        session_id: Id of the transaction this happened in.
        address: 7-bit I2C address that was addressed.
        register: Register (command) byte.
        value: Byte written to that register.
    """

    session_id: int
    address: int
    register: int
    value: int


@dataclass(frozen=True, slots=True)
class BusSettle:
    """A delay requested inside a transaction.

    Attributes:
        session_id: Id of the transaction this happened in.
        seconds: Delay the caller asked for. No time actually passes.
    """

    session_id: int
    seconds: float


@dataclass(frozen=True, slots=True)
class BusWait:
    """A delay requested outside any transaction, while the bus stayed free.

    Attributes:
        session_id: Always :data:`NO_SESSION` — a wait belongs to no transaction.
        seconds: Delay the caller asked for. No time actually passes.
    """

    session_id: int
    seconds: float


type BusEvent = BusWrite | BusRead | BusRegisterWrite | BusSettle | BusWait
"""Anything the fake transport records, in the order it happened."""


class BusResponder(ABC):
    """Supplies replies for reads that a test did not script explicitly.

    Implementations may keep state (pin values, sensor readings) and observe
    writes to decide what the next read should return, which is how the fake
    firmware in :mod:`groveyard.testing.firmware` works. The interface is purely
    byte-level so the transport layer stays free of protocol knowledge.
    """

    @abstractmethod
    def observe_write(self, address: int, payload: bytes) -> None:
        """Record a raw write so the next reply can depend on it.

        Args:
            address: 7-bit I2C address that was addressed.
            payload: Bytes the caller wrote.
        """

    @abstractmethod
    def observe_register_write(self, address: int, register: int, value: int) -> None:
        """Record a register write so the next reply can depend on it.

        Args:
            address: 7-bit I2C address that was addressed.
            register: Register (command) byte.
            value: Byte written to that register.
        """

    @abstractmethod
    def respond(self, address: int, count: int) -> bytes:
        """Produce the bytes a read should return.

        Args:
            address: 7-bit I2C address being read.
            count: Number of bytes the caller asked for.

        Returns:
            Exactly ``count`` bytes.
        """


@dataclass(slots=True)
class FakeSession(BusSession):
    """One transaction against the fake bus.

    Attributes:
        transport: The transport that handed out this session.
        session_id: Monotonic id of this transaction, stamped on every event.
    """

    transport: FakeTransport
    session_id: int

    async def write(self, address: int, payload: bytes) -> None:
        """Record a raw write and show it to the responder.

        Args:
            address: 7-bit I2C address of the target device.
            payload: Bytes to place on the bus.
        """
        await self._suspend()
        self.transport.events.append(BusWrite(self.session_id, address, bytes(payload)))
        if self.transport.responder is not None:
            self.transport.responder.observe_write(address, bytes(payload))

    async def read(self, address: int, count: int) -> bytes:
        """Serve a scripted reply, or ask the responder for one.

        Scripted replies are consumed first, in the order they were queued; when
        the queue is empty the responder is used.

        Args:
            address: 7-bit I2C address of the target device.
            count: Number of bytes to read.

        Returns:
            Exactly ``count`` bytes.

        Raises:
            TransportError: If nothing is queued and no responder is configured,
                or the supplied reply is not ``count`` bytes long.
        """
        await self._suspend()
        data = self.transport.take_reply(address, count)
        self.transport.events.append(BusRead(self.session_id, address, data))
        return data

    async def write_register(self, address: int, register: int, value: int) -> None:
        """Record a register write and show it to the responder.

        Args:
            address: 7-bit I2C address of the target device.
            register: Register (command) byte.
            value: Byte to store in that register.
        """
        await self._suspend()
        self.transport.events.append(BusRegisterWrite(self.session_id, address, register, value))
        if self.transport.responder is not None:
            self.transport.responder.observe_register_write(address, register, value)

    async def _suspend(self) -> None:
        """Yield to the event loop, the way a real bus operation does.

        Real traffic suspends: ``smbus2`` calls hand off to a worker thread and
        delays await. Without an equivalent suspension point here every fake
        transaction would run to completion in one step, and a test asserting
        that transactions do not interleave — or that a task can be cancelled
        mid-transaction — would pass even with the bus lock removed.
        """
        await asyncio.sleep(0)

    async def settle(self, seconds: float) -> None:
        """Record the requested delay without actually waiting.

        Tests assert on recorded delays (for example that an ultrasonic read waits
        ~50 ms) instead of paying for them, which keeps the suite fast and free of
        wall-clock flakiness.

        Args:
            seconds: Delay the caller asked for.
        """
        await self._suspend()
        self.transport.events.append(BusSettle(self.session_id, seconds))


class FakeTransport(Transport):
    """A :class:`~groveyard.transport.base.Transport` that never touches hardware.

    Example:
        ```python
        firmware = FakeBridgeFirmware()
        transport = FakeTransport(responder=firmware)
        async with Board(transport) as board:
            ...
        ```

    Attributes:
        responder: Supplies replies for reads that were not scripted.
        events: Every recorded operation, in order, each tagged with its session.
    """

    def __init__(self, responder: BusResponder | None = None, replies: Iterable[bytes] = ()) -> None:
        """Create the fake bus.

        Args:
            responder: Optional stateful responder used when no scripted reply is
                queued. Without one, every read must be scripted.
            replies: Initial scripted replies, consumed in order.
        """
        super().__init__()
        self.responder = responder
        self.events = []
        self._replies = deque(bytes(reply) for reply in replies)
        self._opened = False
        self._session_count = 0

    @property
    def is_open(self) -> bool:
        """Whether :meth:`open` has been called without a matching :meth:`close`."""
        return self._opened

    @property
    def session_count(self) -> int:
        """How many transactions have been started on this transport."""
        return self._session_count

    @property
    def writes(self) -> list[BusWrite]:
        """Only the raw writes, in order — the usual thing to assert on."""
        return [event for event in self.events if isinstance(event, BusWrite)]

    @property
    def delays(self) -> list[float]:
        """Every delay the transport was asked for, in order.

        Covers both kinds: a :class:`BusSettle` inside a transaction and a
        :class:`BusWait` taken with the bus free.
        """
        return [event.seconds for event in self.events if isinstance(event, BusSettle | BusWait)]

    async def wait(self, seconds: float) -> None:
        """Record a bus-free delay without waiting for it.

        Args:
            seconds: Delay the caller asked for.
        """
        self.events.append(BusWait(NO_SESSION, seconds))

    def events_of(self, session_id: int) -> list[BusEvent]:
        """Return the events recorded inside one transaction.

        Args:
            session_id: Id of the transaction to filter by.

        Returns:
            That transaction's events, in order.
        """
        return [event for event in self.events if event.session_id == session_id]

    def has_interleaved_sessions(self) -> bool:
        """Report whether any transaction was interrupted by another one.

        The bus lock must make every transaction atomic, so a session's events are
        contiguous in the event log. A ``True`` result means the lock was bypassed
        and a reply could reach the wrong task.

        Returns:
            ``True`` if some session's events are not contiguous.
        """
        seen: list[int] = []
        for event in self.events:
            if event.session_id == NO_SESSION:
                continue  # happened between transactions, so it cannot split one
            if not seen or seen[-1] != event.session_id:
                if event.session_id in seen:
                    return True
                seen.append(event.session_id)
        return False

    def queue_reply(self, reply: Sequence[int] | bytes) -> None:
        """Script the bytes the next read will return.

        Args:
            reply: Bytes to hand back, exactly as the device would.
        """
        self._replies.append(bytes(reply))

    def take_reply(self, address: int, count: int) -> bytes:
        """Pop the next scripted reply, or ask the responder for one.

        Args:
            address: 7-bit I2C address being read.
            count: Number of bytes the caller asked for.

        Returns:
            Exactly ``count`` bytes.

        Raises:
            TransportError: If no reply is available, or it has the wrong length.
        """
        if self._replies:
            data = self._replies.popleft()
        elif self.responder is not None:
            data = self.responder.respond(address, count)
        else:
            msg = f"no scripted reply for a {count}-byte read from {address:#04x}"
            raise TransportError(msg)
        if len(data) != count:
            msg = f"scripted reply for {address:#04x} has {len(data)} byte(s), expected {count}"
            raise TransportError(msg)
        return data

    async def _open(self) -> None:
        """Mark the fake bus as open. Called with the bus lock held. Idempotent."""
        self._opened = True

    async def _close(self) -> None:
        """Mark the fake bus as closed. Called with the bus lock held. Idempotent."""
        self._opened = False

    def _create_session(self) -> BusSession:
        """Start a new recorded transaction.

        Returns:
            A :class:`FakeSession` carrying the next session id.

        Raises:
            TransportError: If the transport was closed concurrently, matching
                what the real transport does.
        """
        if not self._opened:
            msg = "transport is not open"
            raise TransportError(msg)
        self._session_count += 1
        return FakeSession(self, self._session_count)
