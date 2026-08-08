"""Tests for the Led driver, against the in-memory fake firmware."""

from __future__ import annotations

import asyncio

import pytest

from frames import CommandLog
from groveyard.board import Board
from groveyard.devices.led import MAX_BRIGHTNESS, MIN_BRIGHTNESS, Led
from groveyard.errors import DeviceClosedError
from groveyard.ports import DigitalPort, PinMode
from groveyard.protocol.commands import DIGITAL_LOW, PWM_MAX_DUTY
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport

PORT = DigitalPort.D5
OTHER_PORT = DigitalPort.D6
HALF_BRIGHTNESS = 0.5
HALF_DUTY = 128


def duty_of(brightness: float) -> int:
    """Return the duty cycle the driver is expected to command for a brightness."""
    return round(brightness * PWM_MAX_DUTY)


async def test_switching_on_drives_full_brightness(board: Board, firmware: FakeBridgeFirmware) -> None:
    led = Led(board, PORT)
    await led.on()
    assert firmware.pwm_outputs[PORT] == PWM_MAX_DUTY
    assert firmware.pin_modes[PORT] == PinMode.OUTPUT
    assert led.brightness == MAX_BRIGHTNESS
    assert led.is_on


async def test_brightness_is_scaled_to_the_duty_cycle(board: Board, firmware: FakeBridgeFirmware) -> None:
    led = Led(board, PORT)
    await led.set_brightness(HALF_BRIGHTNESS)
    assert firmware.pwm_outputs[PORT] == HALF_DUTY
    assert led.brightness == pytest.approx(HALF_BRIGHTNESS)
    assert led.is_on


async def test_switching_off_clears_the_cached_brightness(board: Board, firmware: FakeBridgeFirmware) -> None:
    led = Led(board, PORT)
    await led.set_brightness(0.4)
    await led.off()
    assert firmware.pwm_outputs[PORT] == duty_of(MIN_BRIGHTNESS)
    assert led.brightness == MIN_BRIGHTNESS
    assert not led.is_on
    await led.on()
    assert firmware.pwm_outputs[PORT] == PWM_MAX_DUTY
    assert led.brightness == MAX_BRIGHTNESS


async def test_toggling_treats_any_light_as_on(board: Board, firmware: FakeBridgeFirmware) -> None:
    led = Led(board, PORT)
    await led.set_brightness(0.3)
    assert await led.toggle() is False
    assert firmware.pwm_outputs[PORT] == duty_of(MIN_BRIGHTNESS)
    assert await led.toggle() is True
    assert led.brightness == MAX_BRIGHTNESS


async def test_a_brightness_that_rounds_to_zero_is_reported_as_off(
    board: Board,
    firmware: FakeBridgeFirmware,
) -> None:
    led = Led(board, PORT)
    await led.set_brightness(0.001)
    assert firmware.pwm_outputs[PORT] == 0
    assert not led.is_on


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan")])
async def test_an_out_of_range_brightness_is_rejected(
    board: Board,
    firmware: FakeBridgeFirmware,
    value: float,
) -> None:
    led = Led(board, PORT)
    with pytest.raises(ValueError):
        await led.set_brightness(value)
    assert PORT not in firmware.pwm_outputs
    assert led.brightness == MIN_BRIGHTNESS


async def test_the_output_mode_is_configured_once(board: Board, firmware: FakeBridgeFirmware) -> None:
    led = Led(board, PORT)
    await led.set_brightness(0.2)
    await led.set_brightness(0.8)
    log = CommandLog(firmware)
    assert log.pin_modes(PORT) == [PinMode.OUTPUT]
    assert log.pwm_writes(PORT) == [duty_of(0.2), duty_of(0.8)]


async def test_concurrent_dimming_does_not_tear_the_cached_state(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    led = Led(board, PORT)
    levels = [step / 10 for step in range(1, 11)]
    async with asyncio.TaskGroup() as tasks:
        for level in levels:
            tasks.create_task(led.set_brightness(level))
    log = CommandLog(firmware)
    assert sorted(log.pwm_writes(PORT)) == sorted(duty_of(level) for level in levels)
    assert log.pwm_writes(PORT)[-1] == duty_of(led.brightness)
    assert firmware.pwm_outputs[PORT] == duty_of(led.brightness)
    assert log.pin_modes(PORT) == [PinMode.OUTPUT]
    assert not transport.has_interleaved_sessions()


async def test_two_leds_dim_independently(
    board: Board,
    firmware: FakeBridgeFirmware,
    transport: FakeTransport,
) -> None:
    first = Led(board, PORT)
    second = Led(board, OTHER_PORT)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(first.set_brightness(0.2))
        tasks.create_task(second.set_brightness(0.9))
    assert firmware.pwm_outputs[PORT] == duty_of(0.2)
    assert firmware.pwm_outputs[OTHER_PORT] == duty_of(0.9)
    assert not transport.has_interleaved_sessions()


async def test_a_cancelled_dim_leaves_cache_and_hardware_agreeing(
    board: Board,
    firmware: FakeBridgeFirmware,
) -> None:
    led = Led(board, PORT)
    await led.set_brightness(HALF_BRIGHTNESS)
    task = asyncio.create_task(led.set_brightness(MAX_BRIGHTNESS))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert firmware.pwm_outputs[PORT] == duty_of(led.brightness)
    await led.set_brightness(0.25)
    assert firmware.pwm_outputs[PORT] == duty_of(0.25)
    assert led.brightness == pytest.approx(0.25)


async def test_closing_leaves_the_led_dark(board: Board, firmware: FakeBridgeFirmware) -> None:
    led = Led(board, PORT)
    await led.on()
    await led.close()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert led.brightness == MIN_BRIGHTNESS
    assert not led.is_on
    assert led.is_closed
    with pytest.raises(DeviceClosedError):
        await led.set_brightness(HALF_BRIGHTNESS)


async def test_disconnecting_the_board_darkens_the_led(
    transport: FakeTransport,
    firmware: FakeBridgeFirmware,
) -> None:
    board = Board(transport)
    await board.connect()
    led = Led(board, PORT)
    await led.set_brightness(HALF_BRIGHTNESS)
    await board.disconnect()
    assert firmware.digital_outputs[PORT] == DIGITAL_LOW
    assert led.brightness == MIN_BRIGHTNESS
