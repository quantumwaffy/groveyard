"""Tests for the Buzzer driver, against the in-memory fake firmware."""

from __future__ import annotations

import asyncio

import pytest

from frames import CommandLog
from groveyard.board import Board
from groveyard.devices.buzzer import Buzzer
from groveyard.errors import DeviceClosedError, TransportError
from groveyard.ports import DigitalPort, PinMode
from groveyard.protocol.commands import DIGITAL_HIGH, DIGITAL_LOW
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport

PORT = DigitalPort.D2
SHORT_BEEP_SECONDS = 0.01
ENDLESS_BEEP_SECONDS = 60.0


async def start_beeping(buzzer: Buzzer, seconds: float) -> asyncio.Task[None]:
    """Start a beep in its own task and hand back control once it is sounding.

    The "on" write suspends several times (the fake transport models real bus
    latency), so the loop runs until the buzzer reports itself sounding rather
    than assuming a fixed number of scheduler turns.
    """
    task = asyncio.create_task(buzzer.beep(seconds))
    for _ in range(1000):
        if buzzer.is_on:
            return task
        await asyncio.sleep(0)
    raise AssertionError("the buzzer never started sounding")


async def test_beep_sounds_then_falls_silent(board: Board, firmware: FakeBridgeFirmware) -> None:
    buzzer = Buzzer(board, PORT)
    await buzzer.beep(SHORT_BEEP_SECONDS)
    assert CommandLog(firmware).digital_writes(PORT) == [DIGITAL_HIGH, DIGITAL_LOW]
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not buzzer.is_on


async def test_switching_on_and_off_writes_the_expected_levels(
    board: Board,
    firmware: FakeBridgeFirmware,
) -> None:
    buzzer = Buzzer(board, PORT)
    await buzzer.on()
    assert firmware.digital_outputs[PORT] == DIGITAL_HIGH
    await buzzer.off()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW


@pytest.mark.parametrize("seconds", [0.0, -1.0, float("nan")])
async def test_an_invalid_beep_duration_is_rejected(
    board: Board,
    firmware: FakeBridgeFirmware,
    seconds: float,
) -> None:
    buzzer = Buzzer(board, PORT)
    with pytest.raises(ValueError):
        await buzzer.beep(seconds)
    assert PORT not in firmware.digital_outputs
    assert not buzzer.is_on


async def test_the_output_mode_is_configured_once(board: Board, firmware: FakeBridgeFirmware) -> None:
    buzzer = Buzzer(board, PORT)
    await buzzer.beep(SHORT_BEEP_SECONDS)
    await buzzer.beep(SHORT_BEEP_SECONDS)
    assert CommandLog(firmware).pin_modes(PORT) == [PinMode.OUTPUT]


async def test_a_beep_holds_the_device_lock_for_its_whole_duration(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    buzzer = Buzzer(board, PORT)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(buzzer.beep(SHORT_BEEP_SECONDS))
        for _ in range(1000):
            if buzzer.is_on:
                break
            await asyncio.sleep(0)
        assert buzzer.is_on
        tasks.create_task(buzzer.on())
    assert CommandLog(firmware).digital_writes(PORT) == [DIGITAL_HIGH, DIGITAL_LOW, DIGITAL_HIGH]
    assert buzzer.is_on
    assert not transport.has_interleaved_sessions()


async def test_concurrent_beeps_do_not_overlap(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    buzzer = Buzzer(board, PORT)
    beeps = 3
    async with asyncio.TaskGroup() as tasks:
        for _ in range(beeps):
            tasks.create_task(buzzer.beep(SHORT_BEEP_SECONDS))
    assert CommandLog(firmware).digital_writes(PORT) == [DIGITAL_HIGH, DIGITAL_LOW] * beeps
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not buzzer.is_on
    assert not transport.has_interleaved_sessions()


async def test_a_cancelled_beep_leaves_the_buzzer_silent(board: Board, firmware: FakeBridgeFirmware) -> None:
    buzzer = Buzzer(board, PORT)
    task = await start_beeping(buzzer, ENDLESS_BEEP_SECONDS)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert CommandLog(firmware).digital_writes(PORT) == [DIGITAL_HIGH, DIGITAL_LOW]
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not buzzer.is_on


async def test_the_device_lock_survives_a_cancelled_beep(board: Board, firmware: FakeBridgeFirmware) -> None:
    buzzer = Buzzer(board, PORT)
    task = await start_beeping(buzzer, ENDLESS_BEEP_SECONDS)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await buzzer.beep(SHORT_BEEP_SECONDS)
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW


async def test_closing_silences_the_buzzer(board: Board, firmware: FakeBridgeFirmware) -> None:
    buzzer = Buzzer(board, PORT)
    await buzzer.on()
    await buzzer.close()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert not buzzer.is_on
    assert buzzer.is_closed
    with pytest.raises(DeviceClosedError):
        await buzzer.beep(SHORT_BEEP_SECONDS)


async def test_a_beep_cancelled_twice_still_falls_silent(
    board: Board,
    firmware: FakeBridgeFirmware,
) -> None:
    """The silencing write is shielded, so a repeated cancel cannot abort it.

    A collapsing TaskGroup or a loop shutdown cancels twice; without the shield
    the second one lands inside the silencing write and leaves the buzzer sounding
    with no task left to stop it.
    """
    buzzer = Buzzer(board, PORT)
    task = await start_beeping(buzzer, ENDLESS_BEEP_SECONDS)

    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(1000):
        if firmware.digital_outputs[PORT] == DIGITAL_LOW:
            break
        await asyncio.sleep(0)
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW


async def test_a_bus_failure_while_cancelling_does_not_replace_the_cancellation(
    board: Board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured concurrency depends on the cancellation actually arriving.

    Reporting the bus failure instead would leave an enclosing TaskGroup or
    timeout believing the task ended for an unrelated reason.
    """
    buzzer = Buzzer(board, PORT)
    task = await start_beeping(buzzer, ENDLESS_BEEP_SECONDS)

    async def failing_write(*, state: bool) -> None:
        msg = "bus went away"
        raise TransportError(msg)

    monkeypatch.setattr(buzzer, "_set_state_locked", failing_write)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
