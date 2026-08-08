"""Helper for asserting on the command frames the fake firmware recorded."""

from __future__ import annotations

from typing import TYPE_CHECKING

from groveyard.protocol.commands import BridgeCommand

if TYPE_CHECKING:
    from groveyard.ports import Port
    from groveyard.testing.firmware import FakeBridgeFirmware


class CommandLog:
    """Reads :attr:`FakeBridgeFirmware.commands` in terms of one port."""

    def __init__(self, firmware: FakeBridgeFirmware) -> None:
        """Bind the log to the firmware whose frames it inspects."""
        self._firmware = firmware

    def frames(self, command: BridgeCommand, port: Port) -> list[bytes]:
        """Return every frame of one command addressed to one port, in order."""
        return [frame for frame in self._firmware.commands if frame[0] == int(command) and frame[1] == int(port)]

    def pin_modes(self, port: Port) -> list[int]:
        """Return the mode argument of every ``pin_mode`` frame sent to a port."""
        return [frame[2] for frame in self.frames(BridgeCommand.PIN_MODE, port)]

    def digital_writes(self, port: Port) -> list[int]:
        """Return the level argument of every ``digital_write`` frame sent to a port."""
        return [frame[2] for frame in self.frames(BridgeCommand.DIGITAL_WRITE, port)]

    def pwm_writes(self, port: Port) -> list[int]:
        """Return the duty argument of every ``analog_write`` frame sent to a port."""
        return [frame[2] for frame in self.frames(BridgeCommand.ANALOG_WRITE, port)]

    def digital_reads(self, port: Port) -> int:
        """Return how many ``digital_read`` frames were sent to a port."""
        return len(self.frames(BridgeCommand.DIGITAL_READ, port))
