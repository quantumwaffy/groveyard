"""Tests for the Button driver, against the in-memory fake firmware."""

from __future__ import annotations

import asyncio

import pytest

from frames import CommandLog
from groveyard.board import Board
from groveyard.devices.button import Button
from groveyard.errors import DeviceClosedError, ProtocolError
from groveyard.ports import DigitalPort, PinMode
from groveyard.protocol.commands import BridgeCommand
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport

PORT = DigitalPort.D3
CONCURRENT_READERS = 12


async def test_a_held_button_reads_high(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.digital_inputs[PORT] = 1
    button = Button(board, PORT)
    assert await button.is_pressed() is True
    assert await button.read_value() == 1
    assert firmware.pin_modes[PORT] == PinMode.INPUT


async def test_a_released_button_reads_low(board: Board) -> None:
    button = Button(board, PORT)
    assert await button.is_pressed() is False


async def test_it_names_itself_by_port(board: Board) -> None:
    assert Button(board, PORT).describe() == "Button on D3"


async def test_the_input_mode_is_configured_once(board: Board, firmware: FakeBridgeFirmware) -> None:
    button = Button(board, PORT)
    await button.is_pressed()
    await button.is_pressed()
    log = CommandLog(firmware)
    assert log.pin_modes(PORT) == [PinMode.INPUT]
    assert log.digital_reads(PORT) == 2


async def test_a_not_ready_reply_is_retried(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.digital_inputs[PORT] = 1
    firmware.not_ready_replies = 2
    assert await Button(board, PORT).is_pressed() is True


async def test_a_wrong_echo_byte_surfaces_as_a_protocol_error(board: Board, transport: FakeTransport) -> None:
    button = Button(board, PORT)
    transport.queue_reply(bytes([BridgeCommand.DIGITAL_READ + 1, 1]))
    with pytest.raises(ProtocolError):
        await button.is_pressed()


async def test_concurrent_reads_serialize(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    firmware.digital_inputs[PORT] = 1
    button = Button(board, PORT)
    async with asyncio.TaskGroup() as tasks:
        readers = [tasks.create_task(button.is_pressed()) for _ in range(CONCURRENT_READERS)]
    log = CommandLog(firmware)
    assert all(reader.result() for reader in readers)
    assert log.digital_reads(PORT) == CONCURRENT_READERS
    assert log.pin_modes(PORT) == [PinMode.INPUT]
    assert not transport.has_interleaved_sessions()


async def test_two_buttons_do_not_share_state(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.digital_inputs[DigitalPort.D4] = 1
    pressed = Button(board, DigitalPort.D4)
    released = Button(board, DigitalPort.D5)
    async with asyncio.TaskGroup() as tasks:
        first = tasks.create_task(pressed.is_pressed())
        second = tasks.create_task(released.is_pressed())
    assert first.result() is True
    assert second.result() is False


async def test_a_cancelled_read_leaves_the_button_usable(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.digital_inputs[PORT] = 1
    button = Button(board, PORT)
    task = asyncio.create_task(button.read_value())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await button.is_pressed() is True


async def test_a_closed_button_refuses_reads(board: Board) -> None:
    button = Button(board, PORT)
    await button.close()
    assert button.is_closed
    with pytest.raises(DeviceClosedError):
        await button.read_value()
