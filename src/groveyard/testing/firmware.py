"""An in-memory stand-in for the bridge firmware, for tests.

:class:`FakeBridgeFirmware` plugs into
:class:`~groveyard.transport.fake.FakeTransport` as its responder and answers
bridged commands the way the real board does: it echoes the command id, packs
multi-byte payloads, and can be told to reply "not ready" a few times before
producing a value. Tests set the physical world they want::

    firmware = FakeBridgeFirmware()
    firmware.analog_inputs[AnalogPort.A0] = 512
    async with Board(FakeTransport(responder=firmware)) as board:
        assert await LightSensor(board, AnalogPort.A0).read_raw() == 512

It is shipped with the library rather than hidden in the test suite so that users
can test their own applications without a Raspberry Pi.
"""

from __future__ import annotations

import struct
from typing import Final

from groveyard.protocol.bridge import DHT_PAYLOAD_FORMAT, FirmwareVersion
from groveyard.protocol.commands import (
    BRIDGE_ADDRESS,
    BUS_IDLE_BYTE,
    COMMAND_FRAME_LENGTH,
    DATA_NOT_AVAILABLE,
    BridgeCommand,
)
from groveyard.transport.fake import BusResponder

DEFAULT_FIRMWARE_VERSION: Final[FirmwareVersion] = FirmwareVersion(1, 4, 0)
"""Version reported unless a test asks for another one."""

DEFAULT_DHT_READING: Final[tuple[float, float]] = (21.0, 45.0)
"""Comfortable room conditions, returned by DHT ports a test did not configure."""


class FakeBridgeFirmware(BusResponder):
    """Emulates the ``0x04`` bridge well enough to exercise every driver.

    Inputs are dictionaries keyed by pin number, so a test can describe the world
    (“the button on pin 3 is pressed”) instead of hand-assembling reply frames.
    Outputs are recorded the same way, so a test can assert what the board was
    told to do.

    Attributes:
        version: Version reported by the ``firmware_version`` command.
        digital_inputs: Level each digital pin reads back, defaulting to ``0``.
        analog_inputs: ADC counts each analog pin reads back, defaulting to ``0``.
        ultrasonic_distances: Distance in centimetres per pin, defaulting to ``0``.
        dht_readings: ``(celsius, humidity)`` per pin, defaulting to a room reading.
        pin_modes: Mode last configured per pin, as the firmware recorded it.
        digital_outputs: Level last written per pin.
        pwm_outputs: PWM duty cycle last written per pin.
        commands: Every four-byte command frame received, in order.
        not_ready_replies: How many further reads answer "not ready" before a
            real value is produced. Decremented on each such reply.
    """

    def __init__(self, version: FirmwareVersion = DEFAULT_FIRMWARE_VERSION) -> None:
        """Create a board with every pin idle.

        Args:
            version: Version to report during the connect handshake.
        """
        self.version = version
        self.digital_inputs: dict[int, int] = {}
        self.analog_inputs: dict[int, int] = {}
        self.ultrasonic_distances: dict[int, int] = {}
        self.dht_readings: dict[int, tuple[float, float]] = {}
        self.pin_modes: dict[int, int] = {}
        self.digital_outputs: dict[int, int] = {}
        self.pwm_outputs: dict[int, int] = {}
        self.commands: list[bytes] = []
        self.not_ready_replies = 0
        self._last_command: bytes | None = None

    @property
    def last_command(self) -> bytes | None:
        """The most recent command frame, or ``None`` before the first one."""
        return self._last_command

    def observe_write(self, address: int, payload: bytes) -> None:
        """Apply a command frame, updating output state as the firmware would.

        Args:
            address: Address that was written to. Frames for other addresses
                (native-I2C modules) are ignored.
            payload: The four-byte command frame.

        Raises:
            ValueError: If the frame is not four bytes long, which would mean the
                protocol layer built a malformed command.
        """
        if address != BRIDGE_ADDRESS:
            return
        if len(payload) != COMMAND_FRAME_LENGTH:
            msg = f"bridge command must be {COMMAND_FRAME_LENGTH} bytes, got {len(payload)}: {payload!r}"
            raise ValueError(msg)
        self.commands.append(payload)
        self._last_command = payload
        self._apply(payload)

    def observe_register_write(self, address: int, register: int, value: int) -> None:
        """Ignore native-I2C register writes.

        Those modules keep their state in their own controllers; tests assert on
        the transport's recorded events instead.

        Args:
            address: Address that was written to.
            register: Register (command) byte.
            value: Byte written to that register.
        """

    def respond(self, address: int, count: int) -> bytes:
        """Answer a read the way the firmware would.

        Args:
            address: Address being read. Only the bridge answers.
            count: Number of bytes the caller asked for.

        Returns:
            Exactly ``count`` bytes: an echo byte followed by the payload, or a
            not-ready sentinel.

        Raises:
            ValueError: If a read arrives before any command, or for an address
                this fake does not model.
        """
        if address != BRIDGE_ADDRESS:
            msg = f"nothing is listening at {address:#04x} in this fake"
            raise ValueError(msg)
        if self._last_command is None:
            msg = "a read arrived before any command was written"
            raise ValueError(msg)
        if self.not_ready_replies > 0:
            self.not_ready_replies -= 1
            return self._pad(bytes([DATA_NOT_AVAILABLE]), count)
        command, pin = self._last_command[0], self._last_command[1]
        return self._pad(bytes([command]) + self._payload_for(command, pin), count)

    def _apply(self, frame: bytes) -> None:
        """Update the modelled board state from a command frame.

        Args:
            frame: The four-byte command frame.
        """
        command, pin, value = frame[0], frame[1], frame[2]
        if command == BridgeCommand.PIN_MODE:
            self.pin_modes[pin] = value
        elif command == BridgeCommand.DIGITAL_WRITE:
            self.digital_outputs[pin] = value
        elif command == BridgeCommand.ANALOG_WRITE:
            self.pwm_outputs[pin] = value

    def _payload_for(self, command: int, pin: int) -> bytes:
        """Build the payload that follows the echo byte.

        Args:
            command: Command id being answered.
            pin: Pin the command addressed.

        Returns:
            The payload bytes for that command.

        Raises:
            ValueError: If the command does not produce a reply.
        """
        if command == BridgeCommand.FIRMWARE_VERSION:
            return bytes([self.version.major, self.version.minor, self.version.patch])
        if command == BridgeCommand.DIGITAL_READ:
            return bytes([self.digital_inputs.get(pin, 0)])
        if command == BridgeCommand.ANALOG_READ:
            return self._word(self.analog_inputs.get(pin, 0))
        if command == BridgeCommand.ULTRASONIC_READ:
            return self._word(self.ultrasonic_distances.get(pin, 0))
        if command == BridgeCommand.DHT_READ:
            temperature, humidity = self.dht_readings.get(pin, DEFAULT_DHT_READING)
            return struct.pack(DHT_PAYLOAD_FORMAT, temperature, humidity)
        msg = f"command {command} does not produce a reply"
        raise ValueError(msg)

    def _word(self, value: int) -> bytes:
        """Split a 16-bit value the way the firmware does.

        Args:
            value: Value to split.

        Returns:
            Two bytes, most significant first.
        """
        return bytes([value // 256, value % 256])

    def _pad(self, data: bytes, count: int) -> bytes:
        """Stretch or trim a reply to the number of bytes that was requested.

        A real master always reads a fixed number of bytes; anything the firmware
        did not queue comes back as the idle byte.

        Args:
            data: Bytes the firmware produced.
            count: Number of bytes the caller asked for.

        Returns:
            Exactly ``count`` bytes.
        """
        return data[:count].ljust(count, bytes([BUS_IDLE_BYTE]))
