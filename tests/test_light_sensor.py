"""Tests for the light sensor driver, against the fake bridge firmware."""

from __future__ import annotations

import asyncio
import math

import pytest

from groveyard.board import Board
from groveyard.devices.light_sensor import DARK_RESISTANCE_KOHM, LightSensor
from groveyard.ports import AnalogPort, PinMode
from groveyard.protocol.commands import ADC_MAX_COUNTS, BridgeCommand
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport


def _frames(firmware: FakeBridgeFirmware, command: BridgeCommand, port: AnalogPort) -> list[bytes]:
    return [frame for frame in firmware.commands if frame[0] == command and frame[1] == port]


async def test_read_raw_returns_adc_counts(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 674
    sensor = LightSensor(board, AnalogPort.A0)
    assert await sensor.read_raw() == 674


async def test_read_ratio_normalises_to_full_scale(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 512
    sensor = LightSensor(board, AnalogPort.A0)
    assert await sensor.read_ratio() == pytest.approx(512 / ADC_MAX_COUNTS)


async def test_resistance_follows_the_divider_formula(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A1] = 512
    sensor = LightSensor(board, AnalogPort.A1)
    assert await sensor.read_resistance_kohm() == pytest.approx((1023 - 512) * 10 / 512)


async def test_full_scale_reads_as_zero_resistance(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = ADC_MAX_COUNTS
    sensor = LightSensor(board, AnalogPort.A0)
    assert await sensor.read_raw() == ADC_MAX_COUNTS
    assert await sensor.read_resistance_kohm() == pytest.approx(0.0)


async def test_zero_counts_read_as_infinite_resistance(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 0
    sensor = LightSensor(board, AnalogPort.A0)
    assert await sensor.read_raw() == 0
    resistance = await sensor.read_resistance_kohm()
    assert resistance == DARK_RESISTANCE_KOHM
    assert math.isinf(resistance)


async def test_darker_light_means_higher_resistance(board: Board, firmware: FakeBridgeFirmware) -> None:
    sensor = LightSensor(board, AnalogPort.A0)
    firmware.analog_inputs[AnalogPort.A0] = 800
    bright = await sensor.read_resistance_kohm()
    firmware.analog_inputs[AnalogPort.A0] = 100
    dark = await sensor.read_resistance_kohm()
    assert dark > bright


async def test_pin_mode_is_configured_once(board: Board, firmware: FakeBridgeFirmware) -> None:
    sensor = LightSensor(board, AnalogPort.A2)
    for _ in range(4):
        await sensor.read_raw()
    await sensor.read_resistance_kohm()
    assert len(_frames(firmware, BridgeCommand.PIN_MODE, AnalogPort.A2)) == 1
    assert firmware.pin_modes[AnalogPort.A2] == PinMode.INPUT


async def test_concurrent_reads_on_one_sensor_serialize(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 321
    sensor = LightSensor(board, AnalogPort.A0)
    async with asyncio.TaskGroup() as tasks:
        readings = [tasks.create_task(sensor.read_raw()) for _ in range(8)]
    assert [task.result() for task in readings] == [321] * 8
    assert not transport.has_interleaved_sessions()
    assert len(_frames(firmware, BridgeCommand.PIN_MODE, AnalogPort.A0)) == 1


async def test_different_sensors_read_concurrently(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 111
    firmware.analog_inputs[AnalogPort.A1] = 222
    first = LightSensor(board, AnalogPort.A0)
    second = LightSensor(board, AnalogPort.A1)
    async with asyncio.TaskGroup() as tasks:
        left = tasks.create_task(first.read_raw())
        right = tasks.create_task(second.read_raw())
    assert (left.result(), right.result()) == (111, 222)
    assert not transport.has_interleaved_sessions()


async def test_cancelled_read_leaves_the_sensor_usable(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 404
    sensor = LightSensor(board, AnalogPort.A0)
    task = asyncio.create_task(sensor.read_resistance_kohm())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await sensor.read_raw() == 404


async def test_cancelling_one_waiter_does_not_block_the_others(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 55
    sensor = LightSensor(board, AnalogPort.A0)
    tasks = [asyncio.create_task(sensor.read_raw()) for _ in range(5)]
    tasks[2].cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert [result for result in results if not isinstance(result, BaseException)] == [55] * 4
    assert isinstance(results[2], asyncio.CancelledError)
    assert await sensor.read_raw() == 55
    assert not transport.has_interleaved_sessions()
