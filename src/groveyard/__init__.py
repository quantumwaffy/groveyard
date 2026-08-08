"""groveyard — a modern async Python library for GrovePi+ sensors and actuators.

Everything is asynchronous and safe to share between concurrent tasks: one lock
serialises the I2C bus so transactions cannot interleave, and one lock per device
keeps multi-step operations on the same module atomic.

Example:
    ```python
    import asyncio

    from groveyard import AnalogPort, Board, DigitalPort, Led, LightSensor


    async def main() -> None:
        async with Board.on_i2c() as board:
            led = Led(board, DigitalPort.D4)
            sensor = LightSensor(board, AnalogPort.A0)
            if await sensor.read_raw() < 300:
                await led.on()


    asyncio.run(main())
    ```

Off-device, swap the transport for the in-memory fake and the same code runs on a
laptop; see :mod:`groveyard.testing`.
"""

from groveyard.board import Board
from groveyard.devices import (
    AnalogInputDevice,
    BacklightColor,
    BridgedDevice,
    Button,
    Buzzer,
    Device,
    Dht,
    DhtReading,
    DigitalInputDevice,
    DigitalOutputDevice,
    DisplayRows,
    I2CDevice,
    Led,
    LightSensor,
    PortDevice,
    Potentiometer,
    Relay,
    RgbLcd,
    SoundSensor,
    Ultrasonic,
)
from groveyard.errors import (
    BoardError,
    DeviceClosedError,
    DeviceError,
    DeviceNotReadyError,
    GroveyardError,
    NotConnectedError,
    PortInUseError,
    ProtocolError,
    TransportError,
)
from groveyard.ports import AnalogPort, DigitalPort, PinMode, Port, PortKind
from groveyard.protocol.bridge import FirmwareVersion
from groveyard.protocol.commands import DhtVariant
from groveyard.transport.base import RetryPolicy, Transport
from groveyard.transport.fake import FakeTransport
from groveyard.transport.i2c import SMBusTransport

__version__ = "0.1.0"

__all__ = [
    "AnalogInputDevice",
    "AnalogPort",
    "BacklightColor",
    "Board",
    "BoardError",
    "BridgedDevice",
    "Button",
    "Buzzer",
    "Device",
    "DeviceClosedError",
    "DeviceError",
    "DeviceNotReadyError",
    "Dht",
    "DhtReading",
    "DhtVariant",
    "DigitalInputDevice",
    "DigitalOutputDevice",
    "DigitalPort",
    "DisplayRows",
    "FakeTransport",
    "FirmwareVersion",
    "GroveyardError",
    "I2CDevice",
    "Led",
    "LightSensor",
    "NotConnectedError",
    "PinMode",
    "Port",
    "PortDevice",
    "PortInUseError",
    "PortKind",
    "Potentiometer",
    "ProtocolError",
    "Relay",
    "RetryPolicy",
    "RgbLcd",
    "SMBusTransport",
    "SoundSensor",
    "Transport",
    "TransportError",
    "Ultrasonic",
    "__version__",
]
