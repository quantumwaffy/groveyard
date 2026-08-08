"""Tests for the ultrasonic ranger driver, against the fake firmware."""

from __future__ import annotations

import asyncio

import pytest

from groveyard.board import Board
from groveyard.devices.ultrasonic import (
    ULTRASONIC_MAX_DISTANCE_CM,
    ULTRASONIC_MIN_DISTANCE_CM,
    Ultrasonic,
)
from groveyard.errors import DeviceClosedError, DeviceNotReadyError
from groveyard.ports import DigitalPort
from groveyard.protocol.commands import ULTRASONIC_SETTLE_SECONDS, BridgeCommand
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport

RANGER_PORT = DigitalPort.D5
NO_ECHO_CM = 0


class _TrackingBoard(Board):
    """A board that records how many ultrasonic reads are in flight at once."""

    def __init__(self, transport: FakeTransport) -> None:
        super().__init__(transport)
        self.in_flight = 0
        self.max_in_flight = 0

    async def ultrasonic_read(self, port: DigitalPort) -> int:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)  # a suspension point a missing device lock would let another task through
            return await super().ultrasonic_read(port)
        finally:
            self.in_flight -= 1


def _frames_for(firmware: FakeBridgeFirmware, command: BridgeCommand) -> list[bytes]:
    return [frame for frame in firmware.commands if frame[0] == command]


async def test_read_decodes_the_distance(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 137

    ranger = Ultrasonic(board, RANGER_PORT)

    assert await ranger.read_distance_cm() == 137


async def test_read_decodes_a_16_bit_word(board: Board, firmware: FakeBridgeFirmware) -> None:
    """The firmware sends ``hi * 256 + lo``; 300 cm exercises the high byte."""
    firmware.ultrasonic_distances[RANGER_PORT] = 300

    ranger = Ultrasonic(board, RANGER_PORT)

    assert await ranger.read_distance_cm() == 300


async def test_read_sends_the_ultrasonic_command_with_the_pin(board: Board, firmware: FakeBridgeFirmware) -> None:
    ranger = Ultrasonic(board, RANGER_PORT)

    await ranger.read_distance_cm()

    frames = _frames_for(firmware, BridgeCommand.ULTRASONIC_READ)
    assert frames == [bytes([BridgeCommand.ULTRASONIC_READ, RANGER_PORT, 0, 0])]


async def test_read_does_not_configure_the_pin_mode(board: Board, firmware: FakeBridgeFirmware) -> None:
    """Command 7 flips the pin direction inside the firmware; the host must not."""
    ranger = Ultrasonic(board, RANGER_PORT)

    await ranger.read_distance_cm()

    assert _frames_for(firmware, BridgeCommand.PIN_MODE) == []
    assert RANGER_PORT not in firmware.pin_modes


async def test_read_waits_the_documented_settle_time(board: Board, transport: FakeTransport) -> None:
    ranger = Ultrasonic(board, RANGER_PORT)

    await ranger.read_distance_cm()

    assert transport.delays[-1] == ULTRASONIC_SETTLE_SECONDS
    assert transport.delays.count(ULTRASONIC_SETTLE_SECONDS) == 1


@pytest.mark.parametrize("distance_cm", [ULTRASONIC_MIN_DISTANCE_CM, 200, ULTRASONIC_MAX_DISTANCE_CM])
async def test_in_range_distances_are_returned(
    board: Board,
    firmware: FakeBridgeFirmware,
    distance_cm: int,
) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = distance_cm

    ranger = Ultrasonic(board, RANGER_PORT)

    assert await ranger.read_distance_cm() == distance_cm
    assert ranger.last_distance_cm == distance_cm


@pytest.mark.parametrize(
    "distance_cm",
    [NO_ECHO_CM, ULTRASONIC_MIN_DISTANCE_CM - 1, ULTRASONIC_MAX_DISTANCE_CM + 1, 5000],
)
async def test_out_of_range_distances_read_as_no_measurement(
    board: Board,
    firmware: FakeBridgeFirmware,
    distance_cm: int,
) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = distance_cm

    ranger = Ultrasonic(board, RANGER_PORT)

    assert await ranger.read_distance_cm() is None
    assert ranger.last_distance_cm is None


async def test_raw_read_exposes_out_of_range_values(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 5000

    ranger = Ultrasonic(board, RANGER_PORT)

    assert await ranger.read_raw_distance_cm() == 5000
    assert ranger.last_distance_cm is None


async def test_raw_read_updates_the_cache_when_in_range(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 42

    ranger = Ultrasonic(board, RANGER_PORT)

    assert await ranger.read_raw_distance_cm() == 42
    assert ranger.last_distance_cm == 42


async def test_last_distance_is_cached_without_bus_traffic(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 88
    ranger = Ultrasonic(board, RANGER_PORT)
    assert ranger.last_distance_cm is None

    await ranger.read_distance_cm()
    before = len(firmware.commands)

    assert ranger.last_distance_cm == 88
    assert len(firmware.commands) == before


async def test_not_ready_sentinel_is_retried_transparently(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 55
    firmware.not_ready_replies = 2

    ranger = Ultrasonic(board, RANGER_PORT)

    assert await ranger.read_distance_cm() == 55
    assert len(_frames_for(firmware, BridgeCommand.ULTRASONIC_READ)) == 3


async def test_persistent_not_ready_surfaces_an_error(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.not_ready_replies = 99
    ranger = Ultrasonic(board, RANGER_PORT)

    with pytest.raises(DeviceNotReadyError):
        await ranger.read_distance_cm()

    assert ranger.last_distance_cm is None


async def test_a_failed_read_keeps_the_previous_cached_distance(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 61
    ranger = Ultrasonic(board, RANGER_PORT)
    await ranger.read_distance_cm()

    firmware.not_ready_replies = 99
    with pytest.raises(DeviceNotReadyError):
        await ranger.read_distance_cm()

    assert ranger.last_distance_cm == 61


async def test_reading_a_closed_ranger_is_an_error(board: Board) -> None:
    ranger = Ultrasonic(board, RANGER_PORT)
    await ranger.close()

    with pytest.raises(DeviceClosedError):
        await ranger.read_distance_cm()


async def test_concurrent_reads_on_one_ranger_serialize(
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 123

    async with _TrackingBoard(transport) as board:
        ranger = Ultrasonic(board, RANGER_PORT)
        async with asyncio.TaskGroup() as tasks:
            readers = [tasks.create_task(ranger.read_distance_cm()) for _ in range(8)]
        assert board.max_in_flight == 1

    assert {reader.result() for reader in readers} == {123}
    assert ranger.last_distance_cm == 123
    assert not transport.has_interleaved_sessions()
    assert len(_frames_for(firmware, BridgeCommand.ULTRASONIC_READ)) == 8


async def test_mixed_reads_on_one_ranger_do_not_tear_the_cache(
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 77

    async with _TrackingBoard(transport) as board:
        ranger = Ultrasonic(board, RANGER_PORT)
        async with asyncio.TaskGroup() as tasks:
            for _ in range(4):
                tasks.create_task(ranger.read_distance_cm())
                tasks.create_task(ranger.read_raw_distance_cm())
        assert board.max_in_flight == 1

    assert ranger.last_distance_cm == 77
    assert not transport.has_interleaved_sessions()


async def test_two_rangers_do_not_needlessly_serialize(board: Board, firmware: FakeBridgeFirmware) -> None:
    other_port = DigitalPort.D6
    firmware.ultrasonic_distances[RANGER_PORT] = 10
    firmware.ultrasonic_distances[other_port] = 20
    first = Ultrasonic(board, RANGER_PORT)
    second = Ultrasonic(board, other_port)

    async with asyncio.TaskGroup() as tasks:
        near = tasks.create_task(first.read_distance_cm())
        far = tasks.create_task(second.read_distance_cm())

    assert (near.result(), far.result()) == (10, 20)


async def test_cancellation_mid_read_leaves_the_ranger_usable(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.ultrasonic_distances[RANGER_PORT] = 99
    firmware.not_ready_replies = 1  # forces a retry backoff, a real suspension point mid-operation
    ranger = Ultrasonic(board, RANGER_PORT)

    task = asyncio.create_task(ranger.read_distance_cm())
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ranger.last_distance_cm is None
    assert await ranger.read_distance_cm() == 99
