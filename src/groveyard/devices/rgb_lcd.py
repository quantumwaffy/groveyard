"""Driver for the Grove 16x2 LCD with RGB backlight.

This is the only module in the starter kit that is **not** bridged: it carries two
controllers of its own on the I2C bus — an HD44780-compatible text controller at
``0x3e`` and a PWM backlight controller at ``0x62`` — and is addressed with plain
register writes (``docs/protocol.md`` section 4). It still shares the physical
wires with the bridge, so every exchange goes through
:meth:`groveyard.board.Board.bus_session`, which is the same bus lock all bridged
traffic uses.

Locking
-------

Painting the display is a read-modify-write on the driver's cached rows followed
by up to 34 individual register writes. That is exactly the tearing hazard the
per-device lock exists for: one logical operation (initialise, clear, write both
rows, set colour) is one critical section under ``self._lock``, so two tasks can
never interleave characters on the same panel. Inside that section the bus lock is
taken per transaction — device lock, then bus lock, never the other way round —
and no other device is touched while a session is open.

Every public method acquires the lock and delegates to a ``*_locked`` helper;
``*_locked`` helpers never take the lock, so they can call each other freely
(:class:`asyncio.Lock` is not reentrant).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from groveyard.devices.base import I2CDevice

if TYPE_CHECKING:
    from groveyard.board import Board
    from groveyard.transport.base import BusSession

type BacklightColor = tuple[int, int, int]
"""A backlight colour as ``(red, green, blue)``, each channel ``0..255``."""

type DisplayRows = tuple[str, str]
"""The text of the two rows, top row first, as the driver last wrote it."""

TEXT_ADDRESS: Final[int] = 0x3E
"""I2C address of the HD44780-compatible text controller."""

BACKLIGHT_ADDRESS: Final[int] = 0x62
"""I2C address of the PWM controller driving the RGB backlight."""

COMMAND_REGISTER: Final[int] = 0x80
"""Register the text controller interprets as "the value is a command"."""

DATA_REGISTER: Final[int] = 0x40
"""Register the text controller interprets as "the value is a character"."""

COMMAND_CLEAR: Final[int] = 0x01
"""Clear the whole display and return the cursor to the top-left cell."""

COMMAND_RETURN_HOME: Final[int] = 0x02
"""Move the cursor back to the top-left cell without erasing anything."""

DISPLAY_CONTROL: Final[int] = 0x08
"""Base opcode of the display on/off control command."""

DISPLAY_ON_FLAG: Final[int] = 0x04
"""Bit of :data:`DISPLAY_CONTROL` that switches the panel on, cursor off."""

COMMAND_DISPLAY_ON: Final[int] = DISPLAY_CONTROL | DISPLAY_ON_FLAG
"""Display on, no cursor, no blinking (``docs/protocol.md`` section 4)."""

COMMAND_TWO_LINE_MODE: Final[int] = 0x28
"""Function set: 4-bit interface, two display lines, 5x8 font."""

COMMAND_SECOND_ROW: Final[int] = 0xC0
"""Move the cursor to the first cell of the bottom row."""

BACKLIGHT_MODE1_REGISTER: Final[int] = 0x00
"""First mode register of the backlight controller."""

BACKLIGHT_MODE2_REGISTER: Final[int] = 0x01
"""Second mode register of the backlight controller."""

BACKLIGHT_MODE_NORMAL: Final[int] = 0x00
"""Value both mode registers take for plain, always-on PWM operation."""

BACKLIGHT_OUTPUT_REGISTER: Final[int] = 0x08
"""Register selecting how the controller drives its four outputs."""

BACKLIGHT_OUTPUT_PWM: Final[int] = 0xAA
"""Value putting every output under PWM control, which the colour registers need."""

BACKLIGHT_RED_REGISTER: Final[int] = 4
"""PWM register of the red channel."""

BACKLIGHT_GREEN_REGISTER: Final[int] = 3
"""PWM register of the green channel."""

BACKLIGHT_BLUE_REGISTER: Final[int] = 2
"""PWM register of the blue channel."""

CLEAR_SETTLE_SECONDS: Final[float] = 0.05
"""Time the text controller needs after *clear* or *return home* before more writes.

The controller ignores traffic while it rewrites its DDRAM, so a character sent
too early is simply lost (``docs/protocol.md`` section 4).
"""

COLUMN_COUNT: Final[int] = 16
"""Number of character cells in one row."""

ROW_COUNT: Final[int] = 2
"""Number of rows on the panel."""

COLOR_MIN: Final[int] = 0
"""Lowest value a backlight channel accepts."""

COLOR_MAX: Final[int] = 255
"""Highest value a backlight channel accepts (8-bit PWM duty cycle)."""

BACKLIGHT_OFF: Final[BacklightColor] = (0, 0, 0)
"""The safe state of the backlight: every channel dark."""

DEFAULT_COLOR: Final[BacklightColor] = (COLOR_MAX, COLOR_MAX, COLOR_MAX)
"""Colour applied on initialisation so text is readable without extra setup."""

PRINTABLE_MIN: Final[int] = 0x20
"""Lowest code point the character ROM renders as expected (space)."""

PRINTABLE_MAX: Final[int] = 0x7E
"""Highest code point the character ROM renders as expected (tilde)."""

SUBSTITUTE_CHARACTER: Final[str] = "?"
"""Stand-in for any character the panel's ASCII range cannot show."""

PADDING_CHARACTER: Final[str] = " "
"""Filler written to the cells a row does not use, so old text cannot show through."""

ROW_SEPARATOR: Final[str] = "\n"
"""Character that starts a new row in :meth:`RgbLcd.write_text`."""


class RgbLcd(I2CDevice):
    """The 16x2 Grove LCD with an RGB backlight, on the shared I2C port.

    The driver keeps two pieces of state: the text it last painted and the
    backlight colour it last commanded. Both are updated only after the
    corresponding bus traffic succeeded, so a failed or cancelled write never
    leaves the cache claiming something the panel is not showing.

    Text is written as two full rows: every row is padded to 16 cells, which makes
    a write self-contained (no leftovers from a longer previous message) and means
    the display repairs itself after an interrupted write.

    Example:
        ```python
        async with Board.on_i2c() as board:
            async with RgbLcd(board) as lcd:
                await lcd.set_color(0, 128, 64)
                await lcd.write_lines("groveyard", "ready")
        ```
    """

    def __init__(self, board: Board) -> None:
        """Claim the shared I2C port for this panel.

        The bus is not touched here: the controllers are configured lazily on the
        first operation, or eagerly by :meth:`initialise`.

        Args:
            board: The connection this device operates on.

        Raises:
            PortInUseError: If another live device already holds the I2C port.
        """
        super().__init__(board)
        self._initialised = False
        self._rows: DisplayRows = ("", "")
        self._color: BacklightColor = DEFAULT_COLOR

    @property
    def rows(self) -> DisplayRows:
        """The two rows of text this driver last painted, top row first.

        Characters the panel cannot render have already been substituted and the
        rows truncated to 16 columns, so this is what is actually on the display.
        Trailing padding is not included.
        """
        return self._rows

    @property
    def text(self) -> str:
        """The displayed text as one string, rows joined by a newline."""
        return ROW_SEPARATOR.join(self._rows)

    @property
    def color(self) -> BacklightColor:
        """The backlight colour this driver last commanded, as ``(r, g, b)``.

        Before :meth:`initialise` has run this is :data:`DEFAULT_COLOR`, the colour
        initialisation will apply.
        """
        return self._color

    async def initialise(self) -> None:
        """Configure both controllers and clear the panel.

        Sends display-on/no-cursor, two-line mode and clear to the text controller,
        puts the backlight controller into PWM mode and applies the cached colour
        (:data:`DEFAULT_COLOR` until :meth:`set_color` says otherwise). Idempotent:
        the sequence runs once per device and later calls do no bus traffic at all.
        Calling it is optional — every other operation initialises on demand.

        Takes at least :data:`CLEAR_SETTLE_SECONDS` (50 ms) because of the clear.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            self._require_open()
            await self._ensure_initialised_locked()

    async def clear(self) -> None:
        """Erase the display and move the cursor back to the top-left cell.

        Waits :data:`CLEAR_SETTLE_SECONDS` (50 ms) inside the transaction, as the
        controller drops anything sent while it is clearing
        (``docs/protocol.md`` section 4).

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            self._require_open()
            await self._clear_locked()

    async def write_lines(self, first: str, second: str = "") -> None:
        """Paint the two rows of the display.

        Each row is sanitised, truncated to 16 columns and padded with spaces, so
        the call always leaves the panel showing exactly these two rows and nothing
        of what was there before. Characters outside printable ASCII
        (``0x20..0x7e``) are replaced with :data:`SUBSTITUTE_CHARACTER`; the panel's
        character ROM is not Unicode, so rendering them would be misleading.

        The whole repaint happens under the device lock, so concurrent writers
        cannot mix their characters.

        Args:
            first: Text for the top row. Longer than 16 characters is truncated.
            second: Text for the bottom row. Defaults to blanking that row.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            self._require_open()
            await self._write_rows_locked(first, second)

    async def write_text(self, text: str) -> None:
        """Paint free-form text, breaking it into the two rows.

        Rows are split on :data:`ROW_SEPARATOR` (a newline) and, within a
        paragraph, wrapped every :data:`COLUMN_COUNT` characters. Only the first
        two resulting rows are shown; anything beyond them is dropped, because the
        panel has no more cells. Sanitising,
        truncation and padding are as in :meth:`write_lines`.

        Args:
            text: The message to display.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        first, second = self._split_rows(text)
        await self.write_lines(first, second)

    async def set_color(self, red: int, green: int, blue: int) -> None:
        """Set the backlight colour.

        Args:
            red: Red channel, ``0..255``.
            green: Green channel, ``0..255``.
            blue: Blue channel, ``0..255``.

        Raises:
            ValueError: If any channel is outside ``0..255``. Nothing is written
                and the cached colour is unchanged.
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            TransportError: If the bus itself failed.
        """
        color = (
            self._validate_channel("red", red),
            self._validate_channel("green", green),
            self._validate_channel("blue", blue),
        )
        async with self._lock:
            self._require_open()
            await self._set_color_locked(color)

    async def _shutdown_locked(self) -> None:
        """Leave the panel blank and dark. Called with the lock held.

        A crashed application must not leave a lit display showing stale text, so
        closing clears the text and drives all three backlight channels to zero.

        A panel that was never initialised is already in its safe state — it is
        blank and dark — so closing it does nothing at all. Initialising it just
        to blank it would switch the display *on* for one transaction and cost two
        controller settles. The caches are updated only after the traffic has
        succeeded, so a failed shutdown never reports a dark panel that is still
        lit.

        Raises:
            NotConnectedError: If the board has already been disconnected.
            TransportError: If the bus itself failed.
        """
        if not self._initialised:
            self._rows = ("", "")
            self._color = BACKLIGHT_OFF
            return
        async with self._board.bus_session() as session:
            await self._send_command(session, COMMAND_CLEAR)
        await self._wait_for_controller()
        async with self._board.bus_session() as session:
            await self._send_color(session, BACKLIGHT_OFF)
        self._rows = ("", "")
        self._color = BACKLIGHT_OFF

    async def _wait_for_controller(self) -> None:
        """Give the HD44780 time to finish a clear or a return-home.

        Deliberately **not** a ``session.settle``: unlike a bridged command, no
        reply is waiting to be collected at an address, so nothing about this
        delay requires the bus. Holding the bus lock for 50 ms would stall every
        other device on the board. The device lock is still held, which is what
        actually protects the controller's cursor across the wait
        (``docs/protocol.md`` section 4).

        The wait goes through the board rather than :func:`asyncio.sleep` so that
        it stays observable: the fake transport records it instead of paying for
        it, which keeps tests both honest about timing and fast.
        """
        await self._board.wait(CLEAR_SETTLE_SECONDS)

    async def _ensure_initialised_locked(self) -> None:
        """Run the power-on sequence unless it has already run. Lock held.

        The cached flag is what makes initialisation idempotent, and the device
        lock is what makes reading and setting that flag race-free.
        """
        if self._initialised:
            return
        await self._initialise_locked()

    async def _initialise_locked(self) -> None:
        """Configure both controllers in one transaction. Lock held.

        The order follows ``docs/protocol.md`` section 4: display on, two-line
        mode, clear, then the backlight controller's mode registers and the cached
        colour. The flag is set only after the transaction completed, so a
        cancelled initialisation is simply retried on the next operation (every
        command in the sequence is idempotent).
        """
        async with self._board.bus_session() as session:
            await self._send_command(session, COMMAND_DISPLAY_ON)
            await self._send_command(session, COMMAND_TWO_LINE_MODE)
            await self._send_command(session, COMMAND_CLEAR)
        await self._wait_for_controller()
        async with self._board.bus_session() as session:
            await session.write_register(BACKLIGHT_ADDRESS, BACKLIGHT_MODE1_REGISTER, BACKLIGHT_MODE_NORMAL)
            await session.write_register(BACKLIGHT_ADDRESS, BACKLIGHT_MODE2_REGISTER, BACKLIGHT_MODE_NORMAL)
            await session.write_register(BACKLIGHT_ADDRESS, BACKLIGHT_OUTPUT_REGISTER, BACKLIGHT_OUTPUT_PWM)
            await self._send_color(session, self._color)
        self._rows = ("", "")
        self._initialised = True

    async def _clear_locked(self) -> None:
        """Send the clear command and wait for the controller. Lock held."""
        await self._ensure_initialised_locked()
        async with self._board.bus_session() as session:
            await self._send_command(session, COMMAND_CLEAR)
        await self._wait_for_controller()
        self._rows = ("", "")

    async def _write_rows_locked(self, first: str, second: str) -> None:
        """Repaint both rows in one transaction. Lock held.

        Args:
            first: Text for the top row, before sanitising and truncation.
            second: Text for the bottom row, before sanitising and truncation.
        """
        await self._ensure_initialised_locked()
        rows = (self._prepare_row(first), self._prepare_row(second))
        async with self._board.bus_session() as session:
            await self._send_command(session, COMMAND_RETURN_HOME)
        await self._wait_for_controller()
        async with self._board.bus_session() as session:
            await self._send_row(session, rows[0])
            await self._send_command(session, COMMAND_SECOND_ROW)
            await self._send_row(session, rows[1])
        self._rows = rows

    async def _set_color_locked(self, color: BacklightColor) -> None:
        """Write the three PWM channels in one transaction. Lock held.

        Args:
            color: Already validated ``(red, green, blue)`` triple.
        """
        await self._ensure_initialised_locked()
        async with self._board.bus_session() as session:
            await self._send_color(session, color)
        self._color = color

    async def _send_command(self, session: BusSession, command: int) -> None:
        """Send one command byte to the text controller.

        Args:
            session: The open transaction to write in.
            command: Command opcode, written to :data:`COMMAND_REGISTER`.

        Raises:
            TransportError: If the bus rejects the write.
        """
        await session.write_register(TEXT_ADDRESS, COMMAND_REGISTER, command)

    async def _send_row(self, session: BusSession, row: str) -> None:
        """Write one full row of characters at the current cursor position.

        The row is padded to :data:`COLUMN_COUNT` so every cell is overwritten.

        Args:
            session: The open transaction to write in.
            row: Sanitised text, at most :data:`COLUMN_COUNT` characters.

        Raises:
            TransportError: If the bus rejects a write.
        """
        for character in row.ljust(COLUMN_COUNT, PADDING_CHARACTER):
            await session.write_register(TEXT_ADDRESS, DATA_REGISTER, ord(character))

    async def _send_color(self, session: BusSession, color: BacklightColor) -> None:
        """Write the three backlight channels in the order the controller expects.

        Args:
            session: The open transaction to write in.
            color: Already validated ``(red, green, blue)`` triple.

        Raises:
            TransportError: If the bus rejects a write.
        """
        red, green, blue = color
        await session.write_register(BACKLIGHT_ADDRESS, BACKLIGHT_RED_REGISTER, red)
        await session.write_register(BACKLIGHT_ADDRESS, BACKLIGHT_GREEN_REGISTER, green)
        await session.write_register(BACKLIGHT_ADDRESS, BACKLIGHT_BLUE_REGISTER, blue)

    def _prepare_row(self, text: str) -> str:
        """Make a string safe to send to the character ROM.

        Args:
            text: Raw text for one row.

        Returns:
            At most :data:`COLUMN_COUNT` characters, all in ``0x20..0x7e``.
        """
        sanitised = "".join(
            character if PRINTABLE_MIN <= ord(character) <= PRINTABLE_MAX else SUBSTITUTE_CHARACTER
            for character in text
        )
        return sanitised[:COLUMN_COUNT]

    def _split_rows(self, text: str) -> DisplayRows:
        """Break free-form text into the two rows the panel can show.

        Explicit newlines start a new row; longer paragraphs wrap every
        :data:`COLUMN_COUNT` characters. Rows beyond the second are dropped.

        Args:
            text: The message to lay out.

        Returns:
            The top and bottom row, either of which may be empty.
        """
        rows: list[str] = []
        for paragraph in text.split(ROW_SEPARATOR):
            chunks = [paragraph[start : start + COLUMN_COUNT] for start in range(0, len(paragraph), COLUMN_COUNT)]
            rows.extend(chunks or [""])
            if len(rows) >= ROW_COUNT:
                break
        rows.extend([""] * ROW_COUNT)
        return rows[0], rows[1]

    def _validate_channel(self, name: str, value: int) -> int:
        """Check one backlight channel against the controller's 8-bit range.

        Args:
            name: Channel name, used in the error message.
            value: Requested duty cycle.

        Returns:
            The value itself, so callers can validate inline.

        Raises:
            ValueError: If the value is outside ``0..255``.
        """
        if not COLOR_MIN <= value <= COLOR_MAX:
            msg = f"{name} must be in {COLOR_MIN}..{COLOR_MAX}, got {value}"
            raise ValueError(msg)
        return value
