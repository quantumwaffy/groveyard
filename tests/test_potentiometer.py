"""Tests for the potentiometer driver, against the fake bridge firmware."""

from __future__ import annotations

import asyncio

import pytest

from groveyard.board import Board
from groveyard.devices.potentiometer import (
    ADC_REFERENCE_VOLTS,
    ROTARY_FULL_TRAVEL_DEGREES,
    SUPPLY_VOLTS,
    Potentiometer,
)
from groveyard.ports import AnalogPort, PinMode
from groveyard.protocol.commands import ADC_MAX_COUNTS, BridgeCommand
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport


def _frames(firmware: FakeBridgeFirmware, command: BridgeCommand, port: AnalogPort) -> list[bytes]:
    return [frame for frame in firmware.commands if frame[0] == command and frame[1] == port]


async def test_read_raw_returns_adc_counts(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A2] = 750
    knob = Potentiometer(board, AnalogPort.A2)
    assert await knob.read_raw() == 750


async def test_read_ratio_normalises_to_full_scale(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A2] = 256
    knob = Potentiometer(board, AnalogPort.A2)
    assert await knob.read_ratio() == pytest.approx(256 / ADC_MAX_COUNTS)


async def test_voltage_follows_the_reference_divider(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A2] = 512
    knob = Potentiometer(board, AnalogPort.A2)
    assert await knob.read_voltage() == pytest.approx(512 * ADC_REFERENCE_VOLTS / ADC_MAX_COUNTS)


async def test_degrees_follow_the_protocol_formula(board: Board, firmware: FakeBridgeFirmware) -> None:
    counts = 512
    firmware.analog_inputs[AnalogPort.A2] = counts
    knob = Potentiometer(board, AnalogPort.A2)
    expected = (counts * ADC_REFERENCE_VOLTS / ADC_MAX_COUNTS) * ROTARY_FULL_TRAVEL_DEGREES / SUPPLY_VOLTS
    assert await knob.read_degrees() == pytest.approx(expected)
    assert await knob.read_degrees() == pytest.approx(150.146, abs=1e-3)


async def test_lower_end_stop_reads_zero(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = 0
    knob = Potentiometer(board, AnalogPort.A0)
    assert await knob.read_raw() == 0
    assert await knob.read_voltage() == pytest.approx(0.0)
    assert await knob.read_degrees() == pytest.approx(0.0)


async def test_upper_end_stop_reads_full_travel(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A0] = ADC_MAX_COUNTS
    knob = Potentiometer(board, AnalogPort.A0)
    assert await knob.read_raw() == ADC_MAX_COUNTS
    assert await knob.read_voltage() == pytest.approx(ADC_REFERENCE_VOLTS)
    assert await knob.read_degrees() == pytest.approx(ROTARY_FULL_TRAVEL_DEGREES)


async def test_pin_mode_is_configured_once(board: Board, firmware: FakeBridgeFirmware) -> None:
    knob = Potentiometer(board, AnalogPort.A1)
    await knob.read_raw()
    await knob.read_voltage()
    await knob.read_degrees()
    assert len(_frames(firmware, BridgeCommand.PIN_MODE, AnalogPort.A1)) == 1
    assert firmware.pin_modes[AnalogPort.A1] == PinMode.INPUT


async def test_concurrent_reads_on_one_knob_serialize(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    firmware.analog_inputs[AnalogPort.A2] = ADC_MAX_COUNTS
    knob = Potentiometer(board, AnalogPort.A2)
    async with asyncio.TaskGroup() as tasks:
        angles = [tasks.create_task(knob.read_degrees()) for _ in range(6)]
    assert [task.result() for task in angles] == [pytest.approx(ROTARY_FULL_TRAVEL_DEGREES)] * 6
    assert not transport.has_interleaved_sessions()
    assert len(_frames(firmware, BridgeCommand.PIN_MODE, AnalogPort.A2)) == 1


async def test_different_devices_read_concurrently(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    firmware.analog_inputs[AnalogPort.A1] = 0
    firmware.analog_inputs[AnalogPort.A2] = ADC_MAX_COUNTS
    left = Potentiometer(board, AnalogPort.A1)
    right = Potentiometer(board, AnalogPort.A2)
    async with asyncio.TaskGroup() as tasks:
        low = tasks.create_task(left.read_degrees())
        high = tasks.create_task(right.read_degrees())
    assert low.result() == pytest.approx(0.0)
    assert high.result() == pytest.approx(ROTARY_FULL_TRAVEL_DEGREES)
    assert not transport.has_interleaved_sessions()


async def test_cancelled_read_leaves_the_knob_usable(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A2] = 600
    knob = Potentiometer(board, AnalogPort.A2)
    task = asyncio.create_task(knob.read_degrees())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await knob.read_raw() == 600
