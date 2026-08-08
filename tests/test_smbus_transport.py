"""Tests for SMBusTransport's process-wide same-bus-number guard.

``smbus2`` is faked via ``sys.modules`` injection rather than installed, so
these tests exercise the real ``_open()``/``_close()`` code path (including
the deferred ``import smbus2``) without depending on real hardware or the
optional ``hardware`` extra.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

from groveyard.errors import TransportError
from groveyard.transport.i2c import SMBusTransport

BUS_A = 1
BUS_B = 2

REGISTRY_RACE_WINDOW_SECONDS = 0.05
"""How long to stretch the registry's check-then-add window in the race test."""

BARRIER_TIMEOUT_SECONDS = 5.0
JOIN_TIMEOUT_SECONDS = 10.0


@pytest.fixture(autouse=True)
def _clean_bus_registry() -> None:
    """Reset the process-wide registry so tests cannot see each other's state.

    ``SMBusTransport._open_bus_numbers`` is a ``ClassVar``, shared across every
    instance and every test in this process — a leak from one test would make
    the next one see a bus number as already open for no reason of its own.
    """
    SMBusTransport._open_bus_numbers.clear()


@pytest.fixture
def fake_smbus2(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a fake ``smbus2`` module so ``import smbus2`` succeeds.

    ``SMBus(...)`` returns a fresh mock handle each call; nothing here touches
    real hardware.
    """
    module = MagicMock(name="smbus2")
    module.SMBus.side_effect = lambda bus_number: MagicMock(name=f"SMBus({bus_number})")
    monkeypatch.setitem(sys.modules, "smbus2", module)
    return module


async def test_opening_the_same_bus_number_twice_is_rejected(fake_smbus2: MagicMock) -> None:
    first = SMBusTransport(bus_number=BUS_A)
    second = SMBusTransport(bus_number=BUS_A)

    await first.open()
    with pytest.raises(TransportError, match=f"bus {BUS_A} is already open"):
        await second.open()

    assert first.is_open
    assert not second.is_open
    await first.close()


async def test_different_bus_numbers_do_not_conflict(fake_smbus2: MagicMock) -> None:
    first = SMBusTransport(bus_number=BUS_A)
    second = SMBusTransport(bus_number=BUS_B)

    await first.open()
    await second.open()

    assert first.is_open
    assert second.is_open
    await first.close()
    await second.close()


async def test_closing_releases_the_bus_number_for_reuse(fake_smbus2: MagicMock) -> None:
    first = SMBusTransport(bus_number=BUS_A)
    await first.open()
    await first.close()

    second = SMBusTransport(bus_number=BUS_A)
    await second.open()  # would raise if the registry still thought BUS_A was taken

    assert second.is_open
    await second.close()


async def test_a_failed_open_releases_the_reservation(fake_smbus2: MagicMock) -> None:
    fake_smbus2.SMBus.side_effect = OSError("no such device")
    failed = SMBusTransport(bus_number=BUS_A)

    with pytest.raises(TransportError, match="cannot open I2C bus"):
        await failed.open()
    assert not failed.is_open
    assert BUS_A not in SMBusTransport._open_bus_numbers

    fake_smbus2.SMBus.side_effect = lambda bus_number: MagicMock(name=f"SMBus({bus_number})")
    retry = SMBusTransport(bus_number=BUS_A)
    await retry.open()  # would raise "already open" if the failed attempt had leaked its reservation

    assert retry.is_open
    await retry.close()


async def test_reopening_the_same_instance_is_a_no_op(fake_smbus2: MagicMock) -> None:
    transport = SMBusTransport(bus_number=BUS_A)
    await transport.open()
    await transport.open()  # idempotent: must not raise "already open" against itself

    assert fake_smbus2.SMBus.call_count == 1
    await transport.close()


async def test_a_failed_close_still_releases_the_reservation(fake_smbus2: MagicMock) -> None:
    handle = MagicMock(name="SMBus(1)")
    handle.close.side_effect = OSError("already gone")
    fake_smbus2.SMBus.side_effect = None
    fake_smbus2.SMBus.return_value = handle

    transport = SMBusTransport(bus_number=BUS_A)
    await transport.open()

    with pytest.raises(OSError, match="already gone"):
        await transport.close()

    assert BUS_A not in SMBusTransport._open_bus_numbers

    fake_smbus2.SMBus.return_value = MagicMock(name="SMBus(1) retry")
    retry = SMBusTransport(bus_number=BUS_A)
    await retry.open()  # would raise "already open" if the failed close had leaked the reservation
    await retry.close()


class SlowMembershipSet(set[int]):
    """A set whose membership test is slow, widening the check-then-add window.

    The window between "is this bus number taken?" and "claim it" exists in
    production too — it is just nanoseconds wide, so two threads almost never
    land in it and a plain race test passes on a broken implementation just as
    happily as on a correct one. Stretching that same window turns a
    probabilistic race into a deterministic one, without changing what is being
    tested.
    """

    def __contains__(self, item: object) -> bool:
        """Report membership, slowly."""
        time.sleep(REGISTRY_RACE_WINDOW_SECONDS)
        return super().__contains__(item)


def test_two_event_loops_in_two_threads_cannot_both_open_one_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must hold across threads, not just across tasks in one event loop.

    This is the case an :class:`asyncio.Lock` cannot cover, which is why the
    registry uses a :class:`threading.Lock`: an ``asyncio.Lock``'s uncontended
    path is a plain non-atomic check-and-set, and its contended path parks a
    future on whichever event loop reached it first, so a release from the other
    thread never wakes it. Verified by injecting the old design here: it hangs
    one of the two threads outright.

    Exactly one thread must win, the other must be rejected, and neither may
    hang.
    """
    module = MagicMock(name="smbus2")
    module.SMBus.side_effect = lambda bus_number: MagicMock(name=f"SMBus({bus_number})")
    monkeypatch.setitem(sys.modules, "smbus2", module)
    monkeypatch.setattr(SMBusTransport, "_open_bus_numbers", SlowMembershipSet())

    start = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    async def open_it() -> str:
        transport = SMBusTransport(bus_number=BUS_A)
        try:
            await transport.open()
        except TransportError:
            return "rejected"
        return "opened"

    def worker() -> None:
        start.wait(timeout=BARRIER_TIMEOUT_SECONDS)  # both threads enter the registry together
        result = asyncio.run(open_it())  # a fresh event loop per thread
        with outcomes_lock:
            outcomes.append(result)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT_SECONDS)

    assert not any(thread.is_alive() for thread in threads), "a thread hung — the registry deadlocked"
    assert sorted(outcomes) == ["opened", "rejected"]
