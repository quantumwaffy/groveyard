"""Smoke tests for the transport, protocol and board layers."""

from __future__ import annotations

import asyncio

import pytest

from groveyard.board import Board
from groveyard.devices.base import AnalogInputDevice, DigitalOutputDevice
from groveyard.errors import (
    DeviceNotReadyError,
    NotConnectedError,
    PortInUseError,
    ProtocolError,
    TransportError,
)
from groveyard.ports import AnalogPort, DigitalPort, PinMode
from groveyard.protocol.commands import DHT_SETTLE_SECONDS, ULTRASONIC_SETTLE_SECONDS, BridgeCommand
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport


async def test_connect_performs_version_handshake(board: Board, firmware: FakeBridgeFirmware) -> None:
    assert board.is_connected
    assert str(board.firmware_version) == str(firmware.version)
    assert firmware.commands[0][0] == BridgeCommand.FIRMWARE_VERSION


async def test_operations_require_a_connection(transport: FakeTransport) -> None:
    board = Board(transport)
    with pytest.raises(NotConnectedError):
        await board.digital_read(DigitalPort.D2)


async def test_command_frames_are_four_bytes(board: Board, firmware: FakeBridgeFirmware) -> None:
    await board.set_pin_mode(DigitalPort.D4, PinMode.OUTPUT)
    assert all(len(frame) == 4 for frame in firmware.commands)
    assert firmware.pin_modes[DigitalPort.D4] == PinMode.OUTPUT


async def test_analog_read_decodes_a_16_bit_word(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.analog_inputs[AnalogPort.A1] = 831
    assert await board.analog_read(AnalogPort.A1) == 831


async def test_write_only_commands_are_not_read_back(board: Board, transport: FakeTransport) -> None:
    before = len([event for event in transport.events if type(event).__name__ == "BusRead"])
    await board.digital_write(DigitalPort.D4, 1)
    after = len([event for event in transport.events if type(event).__name__ == "BusRead"])
    assert after == before


async def test_not_ready_sentinel_is_retried(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.not_ready_replies = 2
    firmware.analog_inputs[AnalogPort.A0] = 512
    assert await board.analog_read(AnalogPort.A0) == 512


async def test_persistent_not_ready_surfaces_an_error(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.not_ready_replies = 99
    with pytest.raises(DeviceNotReadyError):
        await board.analog_read(AnalogPort.A0)


async def test_wrong_echo_byte_is_a_protocol_error(board: Board, transport: FakeTransport) -> None:
    transport.queue_reply(bytes([BridgeCommand.DIGITAL_READ + 1, 1]))
    with pytest.raises(ProtocolError):
        await board.digital_read(DigitalPort.D2)


async def test_slow_commands_wait_inside_the_transaction(board: Board, transport: FakeTransport) -> None:
    await board.ultrasonic_read(DigitalPort.D5)
    await board.dht_read(DigitalPort.D6)
    assert ULTRASONIC_SETTLE_SECONDS in transport.delays
    assert DHT_SETTLE_SECONDS in transport.delays


async def test_dht_reading_is_decoded(board: Board, firmware: FakeBridgeFirmware) -> None:
    firmware.dht_readings[DigitalPort.D7] = (23.5, 61.0)
    temperature, humidity = await board.dht_read(DigitalPort.D7)
    assert temperature == pytest.approx(23.5)
    assert humidity == pytest.approx(61.0)


async def test_two_devices_cannot_share_a_port(board: Board) -> None:
    DigitalOutputDevice(board, DigitalPort.D4)
    with pytest.raises(PortInUseError):
        DigitalOutputDevice(board, DigitalPort.D4)


async def test_digital_and_analog_ports_do_not_collide(board: Board, firmware: FakeBridgeFirmware) -> None:
    """``D2`` and ``A2`` share a pin number but are different sockets."""
    output = DigitalOutputDevice(board, DigitalPort.D2)
    sensor = AnalogInputDevice(board, AnalogPort.A2)
    firmware.analog_inputs[AnalogPort.A2] = 700
    await output.on()
    assert await sensor.read_raw() == 700


async def test_concurrent_transactions_never_interleave(board: Board, transport: FakeTransport) -> None:
    async with asyncio.TaskGroup() as tasks:
        for port in (AnalogPort.A0, AnalogPort.A1, AnalogPort.A2):
            tasks.create_task(board.analog_read(port))
            tasks.create_task(board.analog_read(port))
    assert not transport.has_interleaved_sessions()


async def test_closing_an_actuator_leaves_it_off(board: Board, firmware: FakeBridgeFirmware) -> None:
    relay = DigitalOutputDevice(board, DigitalPort.D8)
    await relay.on()
    assert firmware.digital_outputs[DigitalPort.D8] == 1
    await relay.close()
    assert firmware.digital_outputs[DigitalPort.D8] == 0
    assert relay.is_closed


async def test_disconnect_shuts_actuators_down(transport: FakeTransport, firmware: FakeBridgeFirmware) -> None:
    board = Board(transport)
    await board.connect()
    relay = DigitalOutputDevice(board, DigitalPort.D3)
    await relay.on()
    await board.disconnect()
    assert firmware.digital_outputs[DigitalPort.D3] == 0
    assert not transport.is_open


async def test_cancellation_does_not_leak_the_device_lock(board: Board) -> None:
    device = DigitalOutputDevice(board, DigitalPort.D5)
    task = asyncio.create_task(device.on())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await device.on()
    assert device.is_on


async def wait_for_events(transport: FakeTransport, count: int) -> None:
    """Let the loop run until the transport has recorded ``count`` events.

    The fake suspends on every bus operation, so polling the event log interrupts
    a task genuinely in mid-transaction, instead of guessing how many scheduler
    turns a code path takes.
    """
    for _ in range(1000):
        if len(transport.events) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"transport recorded {len(transport.events)} events, expected {count}")


async def test_a_cancelled_close_leaves_the_device_open_for_another_try(
    board: Board,
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    """A cancelled shutdown must not strand an energised actuator.

    Marking the device closed here would make every later ``close()`` — and the
    board's own disconnect sweep — skip it, leaving the relay on for good.
    """
    relay = DigitalOutputDevice(board, DigitalPort.D8)
    await relay.on()
    marker = len(transport.events)

    task = asyncio.create_task(relay.close())
    await wait_for_events(transport, marker + 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not relay.is_closed
    await relay.close()
    assert relay.is_closed
    assert firmware.digital_outputs[DigitalPort.D8] == 0


async def test_a_cancelled_disconnect_still_shuts_everything_down(
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    """Ctrl-C during shutdown must not leave actuators live and the bus open."""
    board = Board(transport)
    await board.connect()
    first = DigitalOutputDevice(board, DigitalPort.D3)
    second = DigitalOutputDevice(board, DigitalPort.D6)
    await first.on()
    await second.on()
    marker = len(transport.events)

    task = asyncio.create_task(board.disconnect())
    await wait_for_events(transport, marker + 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert firmware.digital_outputs[DigitalPort.D3] == 0
    assert firmware.digital_outputs[DigitalPort.D6] == 0
    assert not board.is_connected
    assert not transport.is_open


async def test_concurrent_connects_perform_one_handshake(transport: FakeTransport) -> None:
    board = Board(transport)
    async with asyncio.TaskGroup() as tasks:
        for _ in range(5):
            tasks.create_task(board.connect())
    handshakes = [frame for frame in transport.writes if frame.payload[0] == BridgeCommand.FIRMWARE_VERSION]
    assert len(handshakes) == 1
    await board.disconnect()


async def test_a_closed_transport_refuses_new_sessions(transport: FakeTransport, board: Board) -> None:
    """The fake must behave like the real transport, or tests prove the wrong thing."""
    await board.disconnect()
    with pytest.raises(TransportError):
        async with transport.session():
            pass
