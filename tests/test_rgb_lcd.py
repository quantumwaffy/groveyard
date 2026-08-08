"""Tests for the RGB LCD driver, against the in-memory fake transport."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from groveyard.board import Board
from groveyard.devices.rgb_lcd import (
    BACKLIGHT_ADDRESS,
    BACKLIGHT_BLUE_REGISTER,
    BACKLIGHT_GREEN_REGISTER,
    BACKLIGHT_MODE1_REGISTER,
    BACKLIGHT_MODE2_REGISTER,
    BACKLIGHT_MODE_NORMAL,
    BACKLIGHT_OFF,
    BACKLIGHT_OUTPUT_PWM,
    BACKLIGHT_OUTPUT_REGISTER,
    BACKLIGHT_RED_REGISTER,
    CLEAR_SETTLE_SECONDS,
    COLUMN_COUNT,
    COMMAND_CLEAR,
    COMMAND_DISPLAY_ON,
    COMMAND_REGISTER,
    COMMAND_RETURN_HOME,
    COMMAND_SECOND_ROW,
    COMMAND_TWO_LINE_MODE,
    DATA_REGISTER,
    DEFAULT_COLOR,
    TEXT_ADDRESS,
    RgbLcd,
)
from groveyard.errors import DeviceClosedError, PortInUseError
from groveyard.ports import AnalogPort
from groveyard.transport.fake import BusRegisterWrite, FakeTransport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from groveyard.transport.fake import BusEvent


async def wait_for_events(transport: FakeTransport, count: int) -> None:
    """Let the loop run until the transport has recorded ``count`` events.

    The fake suspends on every bus operation, so polling the event log is a
    deterministic way to interrupt a task in mid-transaction without relying on
    how many scheduler turns a code path happens to take.
    """
    for _ in range(1000):
        if len(transport.events) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"transport recorded {len(transport.events)} events, expected {count}")


def register_writes(events: Sequence[BusEvent]) -> list[BusRegisterWrite]:
    return [event for event in events if isinstance(event, BusRegisterWrite)]


def text_commands(events: Sequence[BusEvent]) -> list[int]:
    return [
        write.value
        for write in register_writes(events)
        if write.address == TEXT_ADDRESS and write.register == COMMAND_REGISTER
    ]


def displayed_characters(events: Sequence[BusEvent]) -> str:
    return "".join(
        chr(write.value)
        for write in register_writes(events)
        if write.address == TEXT_ADDRESS and write.register == DATA_REGISTER
    )


def text_sequence(events: Sequence[BusEvent]) -> list[tuple[str, int]]:
    return [
        ("command" if write.register == COMMAND_REGISTER else "data", write.value)
        for write in register_writes(events)
        if write.address == TEXT_ADDRESS
    ]


def backlight_writes(events: Sequence[BusEvent]) -> list[tuple[int, int]]:
    return [(write.register, write.value) for write in register_writes(events) if write.address == BACKLIGHT_ADDRESS]


async def test_initialise_configures_both_controllers(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)
    before = len(transport.events)

    await lcd.initialise()

    assert text_commands(transport.events[before:]) == [COMMAND_DISPLAY_ON, COMMAND_TWO_LINE_MODE, COMMAND_CLEAR]
    assert backlight_writes(transport.events[before:]) == [
        (BACKLIGHT_MODE1_REGISTER, BACKLIGHT_MODE_NORMAL),
        (BACKLIGHT_MODE2_REGISTER, BACKLIGHT_MODE_NORMAL),
        (BACKLIGHT_OUTPUT_REGISTER, BACKLIGHT_OUTPUT_PWM),
        (BACKLIGHT_RED_REGISTER, DEFAULT_COLOR[0]),
        (BACKLIGHT_GREEN_REGISTER, DEFAULT_COLOR[1]),
        (BACKLIGHT_BLUE_REGISTER, DEFAULT_COLOR[2]),
    ]
    assert CLEAR_SETTLE_SECONDS in transport.delays


async def test_initialise_is_idempotent(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()
    after_first = len(transport.events)

    await lcd.initialise()

    assert len(transport.events) == after_first


async def test_first_use_initialises_lazily(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)

    await lcd.write_lines("hi")
    await lcd.write_lines("again")

    assert text_commands(transport.events).count(COMMAND_DISPLAY_ON) == 1
    assert text_commands(transport.events).count(COMMAND_TWO_LINE_MODE) == 1


async def test_write_lines_paints_both_rows(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()
    before = len(transport.events)

    await lcd.write_lines("hello", "world")

    sequence = text_sequence(transport.events[before:])
    assert sequence[0] == ("command", COMMAND_RETURN_HOME)
    assert sequence[1 + COLUMN_COUNT] == ("command", COMMAND_SECOND_ROW)
    assert displayed_characters(transport.events[before:]) == "hello".ljust(COLUMN_COUNT) + "world".ljust(COLUMN_COUNT)
    assert lcd.rows == ("hello", "world")
    assert lcd.text == "hello\nworld"


async def test_write_lines_blanks_the_bottom_row_by_default(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)
    await lcd.write_lines("first", "second")
    before = len(transport.events)

    await lcd.write_lines("only")

    assert displayed_characters(transport.events[before:]) == "only".ljust(COLUMN_COUNT) + " " * COLUMN_COUNT
    assert lcd.rows == ("only", "")


async def test_write_lines_truncates_and_substitutes_unprintable_characters(
    board: Board,
    transport: FakeTransport,
) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()
    before = len(transport.events)

    await lcd.write_lines("0123456789ABCDEFGHI", "21°C\tok")

    assert lcd.rows == ("0123456789ABCDEF", "21?C?ok")
    assert displayed_characters(transport.events[before:]) == "0123456789ABCDEF" + "21?C?ok".ljust(COLUMN_COUNT)


async def test_write_text_splits_on_newlines(board: Board) -> None:
    lcd = RgbLcd(board)

    await lcd.write_text("hello\nworld")

    assert lcd.rows == ("hello", "world")


async def test_write_text_wraps_at_the_display_width(board: Board) -> None:
    lcd = RgbLcd(board)

    await lcd.write_text("A" * (COLUMN_COUNT + 4))

    assert lcd.rows == ("A" * COLUMN_COUNT, "AAAA")


async def test_write_text_drops_rows_that_do_not_fit(board: Board) -> None:
    lcd = RgbLcd(board)

    await lcd.write_text("one\ntwo\nthree")

    assert lcd.rows == ("one", "two")


async def test_clear_waits_the_documented_settle(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)
    await lcd.write_lines("stale", "text")
    before = len(transport.events)
    delays_before = len(transport.delays)

    await lcd.clear()

    assert text_commands(transport.events[before:]) == [COMMAND_CLEAR]
    assert transport.delays[delays_before:] == [CLEAR_SETTLE_SECONDS]
    assert lcd.rows == ("", "")
    assert lcd.text == "\n"


async def test_set_color_writes_the_pwm_registers(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()
    before = len(transport.events)

    await lcd.set_color(10, 20, 30)

    assert backlight_writes(transport.events[before:]) == [
        (BACKLIGHT_RED_REGISTER, 10),
        (BACKLIGHT_GREEN_REGISTER, 20),
        (BACKLIGHT_BLUE_REGISTER, 30),
    ]
    assert lcd.color == (10, 20, 30)


@pytest.mark.parametrize(
    ("red", "green", "blue"),
    [(-1, 0, 0), (256, 0, 0), (0, -1, 0), (0, 300, 0), (0, 0, -5), (0, 0, 256)],
)
async def test_set_color_rejects_out_of_range_channels(
    board: Board,
    transport: FakeTransport,
    red: int,
    green: int,
    blue: int,
) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()
    before = len(transport.events)

    with pytest.raises(ValueError, match=r"must be in 0\.\.255"):
        await lcd.set_color(red, green, blue)

    assert transport.events[before:] == []
    assert lcd.color == DEFAULT_COLOR


async def test_concurrent_writes_to_one_display_serialize(
    board: Board,
    transport: FakeTransport,
) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()
    before = len(transport.events)
    first = "A" * COLUMN_COUNT + "B" * COLUMN_COUNT
    second = "C" * COLUMN_COUNT + "D" * COLUMN_COUNT

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(lcd.write_lines("A" * COLUMN_COUNT, "B" * COLUMN_COUNT))
        tasks.create_task(lcd.write_lines("C" * COLUMN_COUNT, "D" * COLUMN_COUNT))

    painted = displayed_characters(transport.events[before:])
    assert painted in (first + second, second + first)
    assert not transport.has_interleaved_sessions()


async def test_concurrent_first_use_initialises_only_once(
    board: Board,
    transport: FakeTransport,
) -> None:
    # Lazy initialisation is a check-then-act on cached state spanning two
    # transactions: only the device lock keeps both tasks from configuring the
    # controllers.
    lcd = RgbLcd(board)

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(lcd.write_lines("one"))
        tasks.create_task(lcd.write_lines("two"))

    assert text_commands(transport.events).count(COMMAND_DISPLAY_ON) == 1
    assert text_commands(transport.events).count(COMMAND_TWO_LINE_MODE) == 1


async def test_lcd_traffic_does_not_interleave_with_bridged_traffic(
    board: Board,
    transport: FakeTransport,
) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(lcd.write_lines("bus", "shared"))
        tasks.create_task(board.analog_read(AnalogPort.A0))
        tasks.create_task(board.analog_read(AnalogPort.A1))

    assert not transport.has_interleaved_sessions()


async def test_cancelled_write_leaves_the_device_usable(
    board: Board,
    transport: FakeTransport,
) -> None:
    lcd = RgbLcd(board)
    await lcd.initialise()
    before = len(transport.events)

    task = asyncio.create_task(lcd.write_lines("cancelled", "row"))
    await wait_for_events(transport, before + 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The write really was interrupted in flight: it had opened its transaction and
    # sent the cursor command, but no character reached the panel.
    assert text_commands(transport.events[before:]) == [COMMAND_RETURN_HOME]
    assert displayed_characters(transport.events[before:]) == ""
    assert lcd.rows == ("", "")
    await lcd.write_lines("recovered", "row")
    assert lcd.rows == ("recovered", "row")
    painted = displayed_characters(transport.events[before:])
    assert painted.count("recovered") == 1
    assert "cancelled" not in painted


async def test_close_clears_the_display_and_darkens_the_backlight(board: Board, transport: FakeTransport) -> None:
    lcd = RgbLcd(board)
    await lcd.set_color(200, 100, 50)
    await lcd.write_lines("bye", "now")
    before = len(transport.events)

    await lcd.close()

    assert text_commands(transport.events[before:]) == [COMMAND_CLEAR]
    assert backlight_writes(transport.events[before:]) == [
        (BACKLIGHT_RED_REGISTER, 0),
        (BACKLIGHT_GREEN_REGISTER, 0),
        (BACKLIGHT_BLUE_REGISTER, 0),
    ]
    assert lcd.rows == ("", "")
    assert lcd.color == BACKLIGHT_OFF
    assert lcd.is_closed


async def test_closing_an_untouched_display_touches_the_bus_not_at_all(
    board: Board,
    transport: FakeTransport,
) -> None:
    """An uninitialised panel is blank and dark already, so closing has nothing to do.

    Initialising it in order to blank it would switch the display on for one
    transaction and cost two controller settles on the shared bus.
    """
    lcd = RgbLcd(board)
    before = len(transport.events)

    await lcd.close()

    assert transport.events[before:] == []
    assert lcd.color == BACKLIGHT_OFF
    assert lcd.is_closed


async def test_disconnect_darkens_the_backlight(transport: FakeTransport) -> None:
    board = Board(transport)
    await board.connect()
    lcd = RgbLcd(board)
    await lcd.set_color(255, 0, 0)

    await board.disconnect()

    assert lcd.is_closed
    assert backlight_writes(transport.events)[-3:] == [
        (BACKLIGHT_RED_REGISTER, 0),
        (BACKLIGHT_GREEN_REGISTER, 0),
        (BACKLIGHT_BLUE_REGISTER, 0),
    ]


async def test_using_a_closed_display_is_an_error(board: Board) -> None:
    lcd = RgbLcd(board)
    await lcd.close()

    with pytest.raises(DeviceClosedError):
        await lcd.write_lines("nope")
    with pytest.raises(DeviceClosedError):
        await lcd.set_color(1, 2, 3)
    with pytest.raises(DeviceClosedError):
        await lcd.clear()


async def test_two_displays_cannot_share_the_i2c_port(board: Board) -> None:
    lcd = RgbLcd(board)

    with pytest.raises(PortInUseError):
        RgbLcd(board)

    await lcd.close()
    RgbLcd(board)
