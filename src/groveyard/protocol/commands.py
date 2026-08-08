"""Constants of the ``0x04`` bridge firmware command set.

Everything the wire protocol fixes — command ids, frame size, reply lengths,
per-command timing and the not-ready sentinels — lives here, so no other layer
ever spells out a magic number. The reference is ``docs/protocol.md`` sections 2
and 3, cross-checked against the behaviour of the board's own firmware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, unique
from typing import Final

BRIDGE_ADDRESS: Final[int] = 0x04
"""I2C address of the on-board microcontroller that bridges to the Grove ports."""

COMMAND_FRAME_LENGTH: Final[int] = 4
"""Every bridged command is exactly ``[cmd, arg1, arg2, arg3]``; unused args are 0."""

ECHO_LENGTH: Final[int] = 1
"""Data replies are prefixed with one echo byte repeating the command id."""

DATA_NOT_AVAILABLE: Final[int] = 23
"""First reply byte meaning "the firmware has not serviced the command yet"."""

BUS_IDLE_BYTE: Final[int] = 0xFF
"""First reply byte seen when the firmware has queued nothing; also "not ready"."""

DEFAULT_SETTLE_SECONDS: Final[float] = 0.002
"""Time the firmware needs for a simple digital or analog operation."""

ULTRASONIC_SETTLE_SECONDS: Final[float] = 0.05
"""Time the firmware needs to run an ultrasonic ping and time the echo."""

DHT_SETTLE_SECONDS: Final[float] = 0.25
"""Time the firmware needs for the single-wire DHT exchange."""

ADC_MAX_COUNTS: Final[int] = 1023
"""Full-scale value of the board's 10-bit ADC."""

PWM_MAX_DUTY: Final[int] = 255
"""Full-scale value of the firmware's 8-bit PWM duty cycle."""

DIGITAL_LOW: Final[int] = 0
"""Logic level written or read as "off"."""

DIGITAL_HIGH: Final[int] = 1
"""Logic level written or read as "on"."""

DHT_MIN_CELSIUS: Final[float] = -40.0
"""Lowest temperature any supported DHT variant can report."""

DHT_MAX_CELSIUS: Final[float] = 80.0
"""Highest temperature any supported DHT variant can report."""

DHT_MIN_HUMIDITY: Final[float] = 0.0
"""Lowest relative humidity a DHT sensor can report, in percent."""

DHT_MAX_HUMIDITY: Final[float] = 100.0
"""Highest relative humidity a DHT sensor can report, in percent."""


@unique
class BridgeCommand(IntEnum):
    """Command ids understood by the bridge firmware.

    Only the commands the starter kit needs are listed; the firmware supports
    more (``docs/protocol.md`` section 3).
    """

    DIGITAL_READ = 1
    DIGITAL_WRITE = 2
    ANALOG_READ = 3
    ANALOG_WRITE = 4
    PIN_MODE = 5
    ULTRASONIC_READ = 7
    FIRMWARE_VERSION = 8
    DHT_READ = 40


@unique
class DhtVariant(IntEnum):
    """Sensor variant selector passed as the DHT command's second argument.

    Values follow the firmware: ``0`` for the blue DHT11 that ships with the
    starter kit, ``1`` for the white DHT22.
    """

    DHT11 = 0
    DHT22 = 1


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Everything the transaction loop needs to know about one command.

    Grouping these per command keeps the encoder free of branches and makes the
    hardware facts reviewable in one place against ``docs/protocol.md``.

    Attributes:
        command: The command id written as the first frame byte.
        payload_length: Number of meaningful reply bytes *after* the echo byte.
            Zero means the firmware sends no reply at all.
        settle_seconds: How long to wait between the write and the read.
    """

    command: BridgeCommand
    payload_length: int
    settle_seconds: float = DEFAULT_SETTLE_SECONDS

    @property
    def expects_reply(self) -> bool:
        """Whether the firmware answers this command with data.

        Write-only commands (``pin_mode``, ``digital_write``, ``analog_write``)
        queue nothing: the firmware's request handler has no branch for them, so
        reading afterwards would return an idle ``0xFF`` and look like a
        not-ready reply. Those commands are therefore never read back.
        """
        return self.payload_length > 0

    @property
    def reply_length(self) -> int:
        """Total number of bytes to read, echo byte included."""
        return self.payload_length + ECHO_LENGTH if self.expects_reply else 0


COMMAND_SPECS: Final[dict[BridgeCommand, CommandSpec]] = {
    BridgeCommand.DIGITAL_READ: CommandSpec(BridgeCommand.DIGITAL_READ, payload_length=1),
    BridgeCommand.DIGITAL_WRITE: CommandSpec(BridgeCommand.DIGITAL_WRITE, payload_length=0),
    BridgeCommand.ANALOG_READ: CommandSpec(BridgeCommand.ANALOG_READ, payload_length=2),
    BridgeCommand.ANALOG_WRITE: CommandSpec(BridgeCommand.ANALOG_WRITE, payload_length=0),
    BridgeCommand.PIN_MODE: CommandSpec(BridgeCommand.PIN_MODE, payload_length=0),
    BridgeCommand.ULTRASONIC_READ: CommandSpec(
        BridgeCommand.ULTRASONIC_READ,
        payload_length=2,
        settle_seconds=ULTRASONIC_SETTLE_SECONDS,
    ),
    BridgeCommand.FIRMWARE_VERSION: CommandSpec(BridgeCommand.FIRMWARE_VERSION, payload_length=3),
    BridgeCommand.DHT_READ: CommandSpec(
        BridgeCommand.DHT_READ,
        payload_length=8,
        settle_seconds=DHT_SETTLE_SECONDS,
    ),
}
"""Wire facts for every command the library issues, keyed by command id."""
