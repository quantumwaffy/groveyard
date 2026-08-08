"""Port identifiers for the GrovePi+ HAT.

The board exposes three kinds of sockets (``docs/protocol.md`` section 1):
digital ports ``D2..D8``, analog ports ``A0..A2`` and a shared I2C port. Ports are
enums rather than bare integers so that a wrong socket is a type error instead of
a silent misread, and so that ``D2`` and ``A2`` — which carry the same pin number
on the wire — never collide in the board's port registry.
"""

from __future__ import annotations

from enum import Enum, IntEnum, unique


@unique
class PortKind(Enum):
    """The electrical family a port belongs to."""

    DIGITAL = "digital"
    """Digital ports ``D2..D8``: on/off input, on/off output, or PWM output."""

    ANALOG = "analog"
    """Analog ports ``A0..A2``: 10-bit ADC input, or PWM output."""

    I2C = "i2c"
    """The shared I2C port, used by native-I2C modules such as the RGB LCD."""


@unique
class DigitalPort(IntEnum):
    """A digital Grove socket, numbered by the pin the firmware drives."""

    D2 = 2
    D3 = 3
    D4 = 4
    D5 = 5
    D6 = 6
    D7 = 7
    D8 = 8

    @property
    def kind(self) -> PortKind:
        """Return the electrical family of this port.

        Returns:
            Always :attr:`PortKind.DIGITAL`.
        """
        return PortKind.DIGITAL


@unique
class AnalogPort(IntEnum):
    """An analog Grove socket, numbered by the ADC channel the firmware reads."""

    A0 = 0
    A1 = 1
    A2 = 2

    @property
    def kind(self) -> PortKind:
        """Return the electrical family of this port.

        Returns:
            Always :attr:`PortKind.ANALOG`.
        """
        return PortKind.ANALOG


type Port = DigitalPort | AnalogPort
"""Any addressable Grove socket driven through the ``0x04`` bridge."""


@unique
class PinMode(IntEnum):
    """Direction a bridged pin is configured for.

    Values are the ones the firmware expects in the ``pin_mode`` command
    (``docs/protocol.md`` section 3).
    """

    INPUT = 0
    OUTPUT = 1
