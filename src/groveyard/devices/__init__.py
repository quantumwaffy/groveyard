"""Device drivers: one class per Grove module, plus the bases they share.

Adding a module means adding a class here — no other layer changes.
"""

from groveyard.devices.base import (
    AnalogInputDevice,
    BridgedDevice,
    Device,
    DigitalInputDevice,
    DigitalOutputDevice,
    I2CDevice,
    PortDevice,
)
from groveyard.devices.button import Button
from groveyard.devices.buzzer import Buzzer
from groveyard.devices.dht import Dht, DhtReading
from groveyard.devices.led import Led
from groveyard.devices.light_sensor import LightSensor
from groveyard.devices.potentiometer import Potentiometer
from groveyard.devices.relay import Relay
from groveyard.devices.rgb_lcd import BacklightColor, DisplayRows, RgbLcd
from groveyard.devices.sound_sensor import SoundSensor
from groveyard.devices.ultrasonic import Ultrasonic

__all__ = [
    "AnalogInputDevice",
    "BacklightColor",
    "BridgedDevice",
    "Button",
    "Buzzer",
    "Device",
    "Dht",
    "DhtReading",
    "DigitalInputDevice",
    "DigitalOutputDevice",
    "DisplayRows",
    "I2CDevice",
    "Led",
    "LightSensor",
    "PortDevice",
    "Potentiometer",
    "Relay",
    "RgbLcd",
    "SoundSensor",
    "Ultrasonic",
]
