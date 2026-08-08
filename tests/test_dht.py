"""Tests for the DHT temperature/humidity driver, against the fake firmware."""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from groveyard.board import Board
from groveyard.devices.dht import Dht, DhtReading
from groveyard.errors import DeviceClosedError, DeviceNotReadyError
from groveyard.ports import DigitalPort
from groveyard.protocol.bridge import DEFAULT_NOT_READY_ATTEMPTS, DHT_PAYLOAD_FORMAT
from groveyard.protocol.commands import DHT_SETTLE_SECONDS, BridgeCommand, DhtVariant
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport

SENSOR_PORT = DigitalPort.D7
ROOM_READING = (23.5, 61.0)


class _TrackingBoard(Board):
    """A board that records how many DHT reads are in flight at once."""

    def __init__(self, transport: FakeTransport) -> None:
        super().__init__(transport)
        self.in_flight = 0
        self.max_in_flight = 0

    async def dht_read(self, port: DigitalPort, variant: DhtVariant = DhtVariant.DHT11) -> tuple[float, float]:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)  # a suspension point a missing device lock would let another task through
            return await super().dht_read(port, variant)
        finally:
            self.in_flight -= 1


def _dht_reply(celsius: float, humidity: float) -> bytes:
    return bytes([BridgeCommand.DHT_READ]) + struct.pack(DHT_PAYLOAD_FORMAT, celsius, humidity)


def _frames_for(firmware: FakeBridgeFirmware, command: BridgeCommand) -> list[bytes]:
    return [frame for frame in firmware.commands if frame[0] == command]


async def test_read_decodes_temperature_and_humidity(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[SENSOR_PORT] = ROOM_READING
    sensor = Dht(board, SENSOR_PORT)

    reading = await sensor.read()

    assert reading.temperature_celsius == pytest.approx(23.5)
    assert reading.humidity_percent == pytest.approx(61.0)


async def test_reading_converts_to_fahrenheit() -> None:
    assert DhtReading(temperature_celsius=0.0, humidity_percent=50.0).temperature_fahrenheit == pytest.approx(32.0)
    assert DhtReading(temperature_celsius=100.0, humidity_percent=50.0).temperature_fahrenheit == pytest.approx(212.0)


async def test_read_sends_the_dht_command_with_the_pin(board: Board, firmware: FakeBridgeFirmware) -> None:
    sensor = Dht(board, SENSOR_PORT)

    await sensor.read()

    frames = _frames_for(firmware, BridgeCommand.DHT_READ)
    assert frames == [bytes([BridgeCommand.DHT_READ, SENSOR_PORT, DhtVariant.DHT11, 0])]


async def test_variant_is_sent_as_the_second_argument(board: Board, firmware: FakeBridgeFirmware) -> None:
    sensor = Dht(board, SENSOR_PORT, DhtVariant.DHT22)

    await sensor.read()

    assert sensor.variant is DhtVariant.DHT22
    assert _frames_for(firmware, BridgeCommand.DHT_READ)[0][2] == DhtVariant.DHT22


async def test_read_does_not_configure_the_pin_mode(board: Board, firmware: FakeBridgeFirmware) -> None:
    """Command 40 sets the pin direction inside the firmware; the host must not."""
    sensor = Dht(board, SENSOR_PORT)

    await sensor.read()

    assert _frames_for(firmware, BridgeCommand.PIN_MODE) == []
    assert SENSOR_PORT not in firmware.pin_modes


async def test_read_waits_the_documented_settle_time(board: Board, transport: FakeTransport) -> None:
    sensor = Dht(board, SENSOR_PORT)

    await sensor.read()

    assert transport.delays[-1] == DHT_SETTLE_SECONDS
    assert transport.delays.count(DHT_SETTLE_SECONDS) == 1


async def test_last_reading_is_cached_without_bus_traffic(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[SENSOR_PORT] = ROOM_READING
    sensor = Dht(board, SENSOR_PORT)
    assert sensor.last_reading is None

    reading = await sensor.read()
    before = len(firmware.commands)

    assert sensor.last_reading == reading
    assert len(firmware.commands) == before


async def test_not_ready_sentinel_is_retried_transparently(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[SENSOR_PORT] = ROOM_READING
    firmware.not_ready_replies = 2
    sensor = Dht(board, SENSOR_PORT)

    reading = await sensor.read()

    assert reading == DhtReading(temperature_celsius=23.5, humidity_percent=61.0)
    assert len(_frames_for(firmware, BridgeCommand.DHT_READ)) == 3


async def test_persistent_not_ready_surfaces_an_error(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.not_ready_replies = 99
    sensor = Dht(board, SENSOR_PORT)

    with pytest.raises(DeviceNotReadyError):
        await sensor.read()

    assert sensor.last_reading is None


async def test_a_nan_frame_is_retried_transparently(
    board: Board,
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    """A failed single-wire exchange is another attempt, not an error.

    The rejection lives in ``BridgeProtocol._validate_dht`` and runs as a
    per-attempt validator inside the retry loop, so one bad frame is invisible to
    the caller (``docs/protocol.md`` section 3).
    """
    firmware.dht_readings[SENSOR_PORT] = (19.0, 40.0)
    transport.queue_reply(_dht_reply(math.nan, math.nan))
    sensor = Dht(board, SENSOR_PORT)

    assert await sensor.read() == DhtReading(temperature_celsius=19.0, humidity_percent=40.0)
    assert len(_frames_for(firmware, BridgeCommand.DHT_READ)) == 2


async def test_a_permanently_nan_sensor_surfaces_an_error(board: Board, transport: FakeTransport) -> None:
    for _ in range(DEFAULT_NOT_READY_ATTEMPTS):
        transport.queue_reply(_dht_reply(math.nan, math.nan))
    sensor = Dht(board, SENSOR_PORT)

    with pytest.raises(DeviceNotReadyError):
        await sensor.read()

    assert sensor.last_reading is None


async def test_out_of_range_reading_is_rejected(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[SENSOR_PORT] = (500.0, 61.0)
    sensor = Dht(board, SENSOR_PORT)

    with pytest.raises(DeviceNotReadyError):
        await sensor.read()


async def test_out_of_range_humidity_is_rejected(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[SENSOR_PORT] = (21.0, 130.0)
    sensor = Dht(board, SENSOR_PORT)

    with pytest.raises(DeviceNotReadyError):
        await sensor.read()


async def test_a_failed_read_keeps_the_previous_cached_reading(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[SENSOR_PORT] = ROOM_READING
    sensor = Dht(board, SENSOR_PORT)
    good = await sensor.read()

    firmware.not_ready_replies = 99
    with pytest.raises(DeviceNotReadyError):
        await sensor.read()

    assert sensor.last_reading == good


async def test_reading_a_closed_sensor_is_an_error(board: Board) -> None:
    sensor = Dht(board, SENSOR_PORT)
    await sensor.close()

    with pytest.raises(DeviceClosedError):
        await sensor.read()


async def test_concurrent_reads_on_one_sensor_serialize(
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    firmware.dht_readings[SENSOR_PORT] = ROOM_READING
    expected = DhtReading(temperature_celsius=23.5, humidity_percent=61.0)

    async with _TrackingBoard(transport) as board:
        sensor = Dht(board, SENSOR_PORT)
        async with asyncio.TaskGroup() as tasks:
            readers = [tasks.create_task(sensor.read()) for _ in range(8)]
        assert board.max_in_flight == 1

    assert {reader.result() for reader in readers} == {expected}
    assert sensor.last_reading == expected
    assert not transport.has_interleaved_sessions()
    assert len(_frames_for(firmware, BridgeCommand.DHT_READ)) == 8


async def test_two_sensors_do_not_needlessly_serialize(board: Board, transport: FakeTransport) -> None:
    other_port = DigitalPort.D8
    first = Dht(board, SENSOR_PORT)
    second = Dht(board, other_port)

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(first.read())
        tasks.create_task(second.read())

    assert not transport.has_interleaved_sessions()
    assert first.last_reading is not None
    assert second.last_reading is not None


async def test_cancellation_mid_read_leaves_the_sensor_usable(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[SENSOR_PORT] = ROOM_READING
    firmware.not_ready_replies = 1  # forces a retry backoff, a real suspension point mid-operation
    sensor = Dht(board, SENSOR_PORT)

    task = asyncio.create_task(sensor.read())
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert sensor.last_reading is None
    assert await sensor.read() == DhtReading(temperature_celsius=23.5, humidity_percent=61.0)
