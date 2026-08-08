"""Tests for the Relay driver, against the in-memory fake firmware."""

from __future__ import annotations

import asyncio

import pytest

from frames import CommandLog
from groveyard.board import Board
from groveyard.devices.relay import Relay
from groveyard.errors import DeviceClosedError
from groveyard.ports import DigitalPort, PinMode
from groveyard.protocol.commands import DIGITAL_HIGH, DIGITAL_LOW
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport

PORT = DigitalPort.D6
CONCURRENT_TOGGLES = 10


async def test_closing_the_circuit_energises_the_coil(board: Board, firmware: FakeBridgeFirmware) -> None:
    relay = Relay(board, PORT)
    await relay.close_circuit()
    assert firmware.digital_outputs[PORT] == DIGITAL_HIGH
    assert firmware.pin_modes[PORT] == PinMode.OUTPUT
    assert relay.is_closed_circuit
    assert relay.is_on


async def test_opening_the_circuit_releases_the_coil(board: Board, firmware: FakeBridgeFirmware) -> None:
    relay = Relay(board, PORT)
    await relay.close_circuit()
    await relay.open_circuit()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not relay.is_closed_circuit


async def test_a_closed_circuit_is_not_a_closed_driver(board: Board) -> None:
    relay = Relay(board, PORT)
    await relay.close_circuit()
    assert relay.is_closed_circuit
    assert not relay.is_closed


async def test_the_output_mode_is_configured_once(board: Board, firmware: FakeBridgeFirmware) -> None:
    relay = Relay(board, PORT)
    await relay.close_circuit()
    await relay.open_circuit()
    log = CommandLog(firmware)
    assert log.pin_modes(PORT) == [PinMode.OUTPUT]
    assert log.digital_writes(PORT) == [DIGITAL_HIGH, DIGITAL_LOW]


async def test_concurrent_toggles_do_not_tear_the_cached_state(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    relay = Relay(board, PORT)
    async with asyncio.TaskGroup() as tasks:
        for _ in range(CONCURRENT_TOGGLES):
            tasks.create_task(relay.toggle())
    writes = CommandLog(firmware).digital_writes(PORT)
    assert writes == [DIGITAL_HIGH, DIGITAL_LOW] * (CONCURRENT_TOGGLES // 2)
    assert relay.is_closed_circuit == bool(writes[-1])
    assert firmware.digital_outputs[PORT] == writes[-1]
    assert not transport.has_interleaved_sessions()


async def test_two_relays_switch_independently(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    first = Relay(board, PORT)
    second = Relay(board, DigitalPort.D7)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(first.close_circuit())
        tasks.create_task(second.open_circuit())
    assert firmware.digital_outputs[PORT] == DIGITAL_HIGH
    assert firmware.digital_outputs[DigitalPort.D7] == DIGITAL_LOW
    assert not transport.has_interleaved_sessions()


async def test_a_cancelled_switch_leaves_the_relay_consistent(
    board: Board,
    firmware: FakeBridgeFirmware,
) -> None:
    relay = Relay(board, PORT)
    await relay.close_circuit()
    task = asyncio.create_task(relay.open_circuit())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert firmware.digital_outputs[PORT] == (DIGITAL_HIGH if relay.is_closed_circuit else DIGITAL_LOW)
    await relay.open_circuit()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not relay.is_closed_circuit


async def test_closing_the_driver_de_energises_the_relay(board: Board, firmware: FakeBridgeFirmware) -> None:
    relay = Relay(board, PORT)
    await relay.close_circuit()
    await relay.close()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not relay.is_closed_circuit
    assert relay.is_closed
    with pytest.raises(DeviceClosedError):
        await relay.close_circuit()


async def test_disconnecting_the_board_de_energises_the_relay(
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    board = Board(transport)
    await board.connect()
    relay = Relay(board, PORT)
    await relay.close_circuit()
    await board.disconnect()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not relay.is_closed_circuit
