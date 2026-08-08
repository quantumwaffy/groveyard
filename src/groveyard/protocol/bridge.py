"""Encoding and decoding of the ``0x04`` bridge firmware command set.

This layer turns intent (“read pin 4”) into the exact bytes the firmware expects
and back again. It owns:

* the ``write → settle → read`` transaction shape, run inside one bus session so
  it cannot interleave with other traffic (``docs/protocol.md`` section 2);
* echo-byte validation and the ``23`` / ``255`` not-ready sentinels;
* bounded retries of a whole transaction when the board is not ready yet;
* decoding of multi-byte payloads (ADC counts, distance, DHT floats).

It knows nothing about devices, ports or per-device state — that is the board and
driver layers above it. It holds no lock of its own; atomicity comes entirely from
the transport's bus lock.
"""

from __future__ import annotations

import asyncio
import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from groveyard.errors import DeviceNotReadyError, ProtocolError
from groveyard.protocol.commands import (
    BRIDGE_ADDRESS,
    BUS_IDLE_BYTE,
    COMMAND_FRAME_LENGTH,
    COMMAND_SPECS,
    DATA_NOT_AVAILABLE,
    DHT_MAX_CELSIUS,
    DHT_MAX_HUMIDITY,
    DHT_MIN_CELSIUS,
    DHT_MIN_HUMIDITY,
    BridgeCommand,
    DhtVariant,
)
from groveyard.transport.base import RetryPolicy

if TYPE_CHECKING:
    from collections.abc import Callable

    from groveyard.ports import PinMode
    from groveyard.protocol.commands import CommandSpec
    from groveyard.transport.base import Transport

DEFAULT_NOT_READY_ATTEMPTS: Final[int] = 5
"""How many times a whole transaction is repeated while the board says "not ready"."""

DEFAULT_NOT_READY_BACKOFF_SECONDS: Final[float] = 0.01
"""Base delay between not-ready retries, scaled linearly by attempt number."""

BYTE_MAX: Final[int] = 0xFF
"""Largest value that fits in one frame byte."""

DHT_PAYLOAD_FORMAT: Final[str] = "<2f"
"""Two little-endian IEEE-754 ``float32`` values: temperature then humidity."""


@dataclass(frozen=True, slots=True, order=True)
class FirmwareVersion:
    """Version reported by the bridge firmware during the connect handshake.

    Attributes:
        major: Major version component.
        minor: Minor version component.
        patch: Patch version component.
    """

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        """Return the version in the usual dotted form.

        Returns:
            For example ``"1.4.0"``.
        """
        return f"{self.major}.{self.minor}.{self.patch}"


class BridgeProtocol:
    """Speaks the bridge firmware's command set over a transport.

    The object is stateless apart from its collaborators, so it is safe to share
    between every device on a board: correctness comes from the transport's bus
    lock, which this class holds for the full duration of each transaction.

    Example:
        ```python
        bridge = BridgeProtocol(transport)
        counts = await bridge.analog_read(0)
        ```
    """

    def __init__(
        self,
        transport: Transport,
        address: int = BRIDGE_ADDRESS,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Bind the protocol to a transport.

        Args:
            transport: Bus abstraction that provides locked sessions. Injected
                rather than constructed so tests can pass the in-memory fake.
            address: I2C address of the bridge. Defaults to ``0x04``.
            retry_policy: How often a transaction is repeated while the board
                reports "not ready". Defaults to five attempts with a 10 ms base
                backoff.
        """
        self._transport = transport
        self._address = address
        self._retry_policy = retry_policy or RetryPolicy(
            attempts=DEFAULT_NOT_READY_ATTEMPTS,
            backoff_seconds=DEFAULT_NOT_READY_BACKOFF_SECONDS,
        )

    @property
    def address(self) -> int:
        """I2C address this protocol talks to."""
        return self._address

    async def firmware_version(self) -> FirmwareVersion:
        """Read the firmware version, used as the connect handshake.

        Returns:
            The reported ``major.minor.patch`` version.

        Raises:
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply does not match the command.
            TransportError: If the bus itself failed.
        """
        payload = await self._transact(BridgeCommand.FIRMWARE_VERSION)
        return FirmwareVersion(payload[0], payload[1], payload[2])

    async def set_pin_mode(self, pin: int, mode: PinMode) -> None:
        """Configure a bridged pin as an input or an output.

        The firmware sends no reply to this command, so nothing is read back.

        Args:
            pin: Grove pin number (digital ``2..8``, analog ``0..2``).
            mode: Direction to configure.

        Raises:
            TransportError: If the bus itself failed.
        """
        await self._transact(BridgeCommand.PIN_MODE, pin, int(mode))

    async def digital_read(self, pin: int) -> int:
        """Read the logic level of a digital pin.

        Args:
            pin: Grove pin number (``2..8``).

        Returns:
            ``0`` for low, ``1`` for high.

        Raises:
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply does not match the command.
            TransportError: If the bus itself failed.
        """
        payload = await self._transact(BridgeCommand.DIGITAL_READ, pin)
        return payload[0]

    async def digital_write(self, pin: int, value: int) -> None:
        """Drive a digital pin high or low.

        Args:
            pin: Grove pin number (``2..8``).
            value: ``0`` for low, ``1`` for high.

        Raises:
            ValueError: If ``value`` is not a byte.
            TransportError: If the bus itself failed.
        """
        await self._transact(BridgeCommand.DIGITAL_WRITE, pin, value)

    async def analog_read(self, pin: int) -> int:
        """Read the 10-bit ADC value of an analog pin.

        Args:
            pin: Analog channel number (``0..2``).

        Returns:
            Raw counts in ``0..1023``.

        Raises:
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply does not match the command.
            TransportError: If the bus itself failed.
        """
        payload = await self._transact(BridgeCommand.ANALOG_READ, pin)
        return self._decode_word(payload)

    async def analog_write(self, pin: int, value: int) -> None:
        """Set the PWM duty cycle of a pin.

        Args:
            pin: Grove pin number the firmware can PWM.
            value: Duty cycle in ``0..255``.

        Raises:
            ValueError: If ``value`` is not a byte.
            TransportError: If the bus itself failed.
        """
        await self._transact(BridgeCommand.ANALOG_WRITE, pin, value)

    async def ultrasonic_read(self, pin: int) -> int:
        """Trigger an ultrasonic ping and read the measured distance.

        The firmware needs roughly 50 ms between the write and the read; that
        delay happens inside the bus session (``docs/protocol.md`` section 3).

        Args:
            pin: Grove pin number the ranger is plugged into.

        Returns:
            Distance in centimetres, as reported by the firmware.

        Raises:
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply does not match the command.
            TransportError: If the bus itself failed.
        """
        payload = await self._transact(BridgeCommand.ULTRASONIC_READ, pin)
        return self._decode_word(payload)

    async def dht_read(self, pin: int, variant: DhtVariant = DhtVariant.DHT11) -> tuple[float, float]:
        """Read temperature and humidity from a DHT sensor.

        Implausible results (``NaN`` or values outside the sensors' physical
        range) mean the single-wire exchange failed; they are treated as "not
        ready" and retried rather than returned (``docs/protocol.md`` section 3).

        Args:
            pin: Grove pin number the sensor is plugged into.
            variant: Sensor variant, which the firmware needs to decode the wire
                format.

        Returns:
            A ``(temperature_celsius, humidity_percent)`` pair.

        Raises:
            DeviceNotReadyError: If every attempt produced an implausible reading.
            ProtocolError: If the reply does not match the command.
            TransportError: If the bus itself failed.
        """
        payload = await self._transact(
            BridgeCommand.DHT_READ,
            pin,
            int(variant),
            validate=self._validate_dht,
        )
        return self._decode_dht(payload)

    async def _transact(
        self,
        command: BridgeCommand,
        arg1: int = 0,
        arg2: int = 0,
        arg3: int = 0,
        validate: Callable[[bytes], None] | None = None,
    ) -> bytes:
        """Run one command as an atomic bus transaction, retrying while not ready.

        The write, the settle delay and the read happen inside a single bus
        session, so no other task can read this command's reply. Decoding happens
        after the session is released, keeping the critical section minimal. The
        whole transaction — not just the read — is repeated when the board
        answers with a not-ready sentinel, because the firmware discards the
        pending command once it has replied.

        Args:
            command: Command to issue.
            arg1: First argument byte, usually the pin.
            arg2: Second argument byte.
            arg3: Third argument byte.
            validate: Optional extra check on the decoded payload. It raises
                :class:`~groveyard.errors.DeviceNotReadyError` for a reply that is
                well-formed but implausible, which is how a failed sensor exchange
                (a DHT frame full of ``NaN``) becomes a retry rather than an error.

        Returns:
            The reply payload with the echo byte stripped; empty for write-only
            commands.

        Raises:
            ValueError: If any argument does not fit in a byte.
            DeviceNotReadyError: If the board reported "not ready", or ``validate``
                rejected the payload, on every attempt.
            ProtocolError: If the reply's echo byte did not match the command.
            TransportError: If the bus itself failed.
        """
        spec = COMMAND_SPECS[command]
        frame = self._encode(command, arg1, arg2, arg3)
        not_ready: DeviceNotReadyError | None = None
        for attempt in range(1, self._retry_policy.attempts + 1):
            delay = self._retry_policy.delay_before(attempt)
            if delay:
                await asyncio.sleep(delay)
            reply = await self._exchange(spec, frame)
            if not spec.expects_reply:
                return b""
            try:
                payload = self._decode(spec, reply)
                if validate is not None:
                    validate(payload)
            except DeviceNotReadyError as error:
                not_ready = error
            else:
                return payload
        msg = f"board did not answer {command.name} after {self._retry_policy.attempts} attempt(s)"
        raise DeviceNotReadyError(msg) from not_ready

    async def _exchange(self, spec: CommandSpec, frame: bytes) -> bytes:
        """Perform one write/settle/read cycle inside a single bus session.

        Args:
            spec: Wire facts for the command being issued.
            frame: The four command bytes to write.

        Returns:
            The raw reply, echo byte included; empty for write-only commands.

        Raises:
            TransportError: If the bus itself failed.
        """
        async with self._transport.session() as bus:
            await bus.write(self._address, frame)
            await bus.settle(spec.settle_seconds)
            if not spec.expects_reply:
                return b""
            return await bus.read(self._address, spec.reply_length)

    def _encode(self, command: BridgeCommand, arg1: int, arg2: int, arg3: int) -> bytes:
        """Build the fixed-width command frame.

        Args:
            command: Command id for the first byte.
            arg1: First argument byte.
            arg2: Second argument byte.
            arg3: Third argument byte.

        Returns:
            Exactly ``COMMAND_FRAME_LENGTH`` bytes, unused arguments padded with 0.

        Raises:
            ValueError: If any argument does not fit in a byte.
        """
        args = (arg1, arg2, arg3)
        for position, value in enumerate(args, start=1):
            if not 0 <= value <= BYTE_MAX:
                msg = f"argument {position} of {command.name} must be in 0..{BYTE_MAX}, got {value}"
                raise ValueError(msg)
        frame = bytes((int(command), *args))
        return frame.ljust(COMMAND_FRAME_LENGTH, b"\x00")

    def _decode(self, spec: CommandSpec, reply: bytes) -> bytes:
        """Validate a reply and strip its echo byte.

        Args:
            spec: Wire facts for the command that was issued.
            reply: Raw bytes read back from the board.

        Returns:
            The payload after the echo byte.

        Raises:
            DeviceNotReadyError: If the reply is a not-ready sentinel.
            ProtocolError: If the reply is short or its echo byte is wrong.
        """
        if len(reply) != spec.reply_length:
            msg = f"{spec.command.name} reply has {len(reply)} byte(s), expected {spec.reply_length}"
            raise ProtocolError(msg)
        if reply[0] in (DATA_NOT_AVAILABLE, BUS_IDLE_BYTE):
            msg = f"board is not ready to answer {spec.command.name} (sentinel {reply[0]})"
            raise DeviceNotReadyError(msg)
        if reply[0] != int(spec.command):
            msg = f"{spec.command.name} reply echoed command {reply[0]}, expected {int(spec.command)}"
            raise ProtocolError(msg)
        return reply[1:]

    def _decode_word(self, payload: bytes) -> int:
        """Decode a big-endian 16-bit value.

        Args:
            payload: Exactly two bytes, most significant first.

        Returns:
            The combined value.
        """
        return payload[0] * 256 + payload[1]

    def _decode_dht(self, payload: bytes) -> tuple[float, float]:
        """Decode a DHT reading, re-checking that it is plausible.

        Args:
            payload: Eight bytes holding two little-endian ``float32`` values.

        Returns:
            A ``(temperature_celsius, humidity_percent)`` pair.

        Raises:
            DeviceNotReadyError: If either value is ``NaN`` or physically
                implausible, which means the sensor exchange failed.
        """
        self._validate_dht(payload)
        temperature, humidity = struct.unpack(DHT_PAYLOAD_FORMAT, payload)
        return float(temperature), float(humidity)

    def _validate_dht(self, payload: bytes) -> None:
        """Reject a DHT payload the sensor cannot plausibly have produced.

        A failed single-wire exchange shows up as ``NaN`` or as a wildly
        out-of-range value rather than as a bus error, so this runs as the
        per-attempt validator of :meth:`_transact` and turns such a frame into
        another attempt (``docs/protocol.md`` section 3).

        Args:
            payload: Eight bytes holding two little-endian ``float32`` values.

        Raises:
            DeviceNotReadyError: If either value is ``NaN`` or physically
                implausible.
        """
        temperature, humidity = struct.unpack(DHT_PAYLOAD_FORMAT, payload)
        if math.isnan(temperature) or math.isnan(humidity):
            msg = "DHT reading contains NaN; the sensor exchange failed"
            raise DeviceNotReadyError(msg)
        if not DHT_MIN_CELSIUS <= temperature <= DHT_MAX_CELSIUS:
            msg = f"DHT temperature {temperature} °C is outside {DHT_MIN_CELSIUS}..{DHT_MAX_CELSIUS} °C"
            raise DeviceNotReadyError(msg)
        if not DHT_MIN_HUMIDITY <= humidity <= DHT_MAX_HUMIDITY:
            msg = f"DHT humidity {humidity} % is outside {DHT_MIN_HUMIDITY}..{DHT_MAX_HUMIDITY} %"
            raise DeviceNotReadyError(msg)
