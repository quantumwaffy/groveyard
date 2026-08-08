"""Tests for the sound sensor driver, against the fake bridge firmware."""

from __future__ import annotations

import asyncio

import pytest

from groveyard.board import Board
from groveyard.devices.light_sensor import LightSensor
from groveyard.devices.sound_sensor import DEFAULT_WINDOW_SIZE, MIN_WINDOW_SIZE, SoundSensor
from groveyard.ports import AnalogPort, PinMode
from groveyard.protocol.commands import ADC_MAX_COUNTS, BridgeCommand
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport


def _frames(firmware: FakeBridgeFirmware, command: BridgeCommand, port: AnalogPort) -> list[bytes]:
    return [frame for frame in firmware.commands if frame[0] == command and frame[1] == port]


async def test_read_raw_returns_adc_counts(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A1] = 613
    sensor = SoundSensor(board, AnalogPort.A1)
    assert await sensor.read_raw() == 613


async def test_read_ratio_normalises_to_full_scale(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A1] = ADC_MAX_COUNTS
    sensor = SoundSensor(board, AnalogPort.A1)
    assert await sensor.read_ratio() == pytest.approx(1.0)


async def test_default_window_size_is_used(board: Board) -> None:
    sensor = SoundSensor(board, AnalogPort.A0)
    assert sensor.window_size == DEFAULT_WINDOW_SIZE


async def test_window_size_must_be_positive(board: Board) -> None:
    with pytest.raises(ValueError, match="window_size"):
        SoundSensor(board, AnalogPort.A0, window_size=MIN_WINDOW_SIZE - 1)


async def test_rejected_window_size_does_not_claim_the_port(board: Board) -> None:
    with pytest.raises(ValueError, match="window_size"):
        SoundSensor(board, AnalogPort.A0, window_size=0)
    assert SoundSensor(board, AnalogPort.A0).window_size == DEFAULT_WINDOW_SIZE


async def test_average_of_a_steady_signal_is_that_signal(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A1] = 480
    sensor = SoundSensor(board, AnalogPort.A1, window_size=4)
    assert await sensor.read_average() == pytest.approx(480.0)


async def test_average_takes_exactly_window_size_samples(board: Board, firmware: FakeBridgeFirmware) -> None:
    window = 5
    firmware.analog_inputs[AnalogPort.A1] = 300
    sensor = SoundSensor(board, AnalogPort.A1, window_size=window)
    await sensor.read_average()
    assert len(_frames(firmware, BridgeCommand.ANALOG_READ, AnalogPort.A1)) == window
    assert len(_frames(firmware, BridgeCommand.PIN_MODE, AnalogPort.A1)) == 1
    assert firmware.pin_modes[AnalogPort.A1] == PinMode.INPUT


async def test_window_of_one_is_a_plain_read(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 0
    sensor = SoundSensor(board, AnalogPort.A0, window_size=MIN_WINDOW_SIZE)
    assert await sensor.read_average() == pytest.approx(0.0)
    assert len(_frames(firmware, BridgeCommand.ANALOG_READ, AnalogPort.A0)) == 1


async def test_average_at_full_scale(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = ADC_MAX_COUNTS
    sensor = SoundSensor(board, AnalogPort.A0, window_size=3)
    assert await sensor.read_average() == pytest.approx(float(ADC_MAX_COUNTS))


async def test_concurrent_averages_on_one_sensor_serialize(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    window, readers = 4, 3
    firmware.analog_inputs[AnalogPort.A1] = 250
    sensor = SoundSensor(board, AnalogPort.A1, window_size=window)
    async with asyncio.TaskGroup() as tasks:
        averages = [tasks.create_task(sensor.read_average()) for _ in range(readers)]
    assert [task.result() for task in averages] == [pytest.approx(250.0)] * readers
    assert len(_frames(firmware, BridgeCommand.ANALOG_READ, AnalogPort.A1)) == window * readers
    assert not transport.has_interleaved_sessions()


async def test_average_is_not_torn_by_another_device(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    window = 6
    firmware.analog_inputs[AnalogPort.A1] = 700
    firmware.analog_inputs[AnalogPort.A0] = 120
    sensor = SoundSensor(board, AnalogPort.A1, window_size=window)
    light = LightSensor(board, AnalogPort.A0)
    async with asyncio.TaskGroup() as tasks:
        average = tasks.create_task(sensor.read_average())
        neighbours = [tasks.create_task(light.read_raw()) for _ in range(3)]
    assert average.result() == pytest.approx(700.0)
    assert [task.result() for task in neighbours] == [120] * 3
    assert len(_frames(firmware, BridgeCommand.ANALOG_READ, AnalogPort.A1)) == window
    assert len(_frames(firmware, BridgeCommand.ANALOG_READ, AnalogPort.A0)) == 3
    assert not transport.has_interleaved_sessions()


async def test_cancelled_average_leaves_the_sensor_usable(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A1] = 88
    sensor = SoundSensor(board, AnalogPort.A1, window_size=3)
    task = asyncio.create_task(sensor.read_average())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await sensor.read_average() == pytest.approx(88.0)
    assert sensor.window_size == 3
