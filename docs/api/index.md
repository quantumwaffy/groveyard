# API reference

This section is generated from the library's own docstrings — every class,
method and constant is documented in one place, and stays in sync with the
code by construction (see [mkdocstrings](https://mkdocstrings.github.io/)).

If you only need the everyday surface, everything below is also importable
directly from the top-level package:

```python
from groveyard import (
    Board,
    DigitalPort,
    AnalogPort,
    PinMode,
    Button,
    Led,
    Buzzer,
    Relay,
    LightSensor,
    SoundSensor,
    Potentiometer,
    Dht,
    DhtReading,
    Ultrasonic,
    RgbLcd,
    FakeTransport,
    SMBusTransport,
    GroveyardError,
    TransportError,
    ProtocolError,
    DeviceNotReadyError,
)
```

The pages in this section are organised by layer, matching
[the architecture overview](../architecture/index.md):

| Layer | Page |
|---|---|
| Board (lifecycle, port registry) | [Board](board.md) |
| Ports and pin modes | [Ports](ports.md) |
| Typed error hierarchy | [Errors](errors.md) |
| Transport (bus, locks, I/O backends) | [Transport](transport.md) |
| Protocol (bridge command encoding) | [Protocol](protocol.md) |
| Device drivers | [Devices](devices/base.md) |
| Test doubles shipped with the library | [Testing utilities](testing.md) |
