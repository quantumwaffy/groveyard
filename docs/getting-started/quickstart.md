# Quickstart

## Connect to the board

[`Board`][groveyard.Board] is the connection object. Use it as an async
context manager so the bus is always closed and every actuator is driven back
to a safe state, even if your code raises:

```python
import asyncio

from groveyard import Board


async def main() -> None:
    async with Board.on_i2c() as board:
        print(board.firmware_version)


asyncio.run(main())
```

`Board.on_i2c()` builds a board wired to real hardware on `/dev/i2c-1`. It is
not connected yet — entering the `async with` block runs
[`connect()`][groveyard.Board.connect], which opens the bus and performs the
firmware-version handshake.

## Drive a sensor and an actuator

Construct a driver by handing it the board and the port the module is plugged
into. Construction claims the port immediately, so a second driver on the
same socket fails fast with [`PortInUseError`][groveyard.PortInUseError]
instead of silently corrupting the first one's state:

```python
from groveyard import AnalogPort, Board, DigitalPort, Led, LightSensor


async def main() -> None:
    async with Board.on_i2c() as board:
        sensor = LightSensor(board, AnalogPort.A0)
        led = Led(board, DigitalPort.D5)

        raw = await sensor.read_raw()  # 0..1023, always available
        ratio = await sensor.read_ratio()  # 0.0..1.0
        kohm = await sensor.read_resistance_kohm()

        if raw < 300:
            await led.set_brightness(0.6)
```

Every analog driver keeps the raw ADC reading reachable — conversions like
`read_resistance_kohm()` are convenience on top, never a replacement. See the
[API reference](../api/index.md) for what each of the ten drivers exposes.

## Run things concurrently

Two tasks on **different** devices may run concurrently; they only briefly
contend on the shared bus. Two tasks on the **same** device serialise
automatically — you cannot tear a driver's state by forgetting to lock
something, because the driver already did:

```python
import asyncio

from groveyard import DigitalPort, RgbLcd, Ultrasonic


async def main() -> None:
    async with Board.on_i2c() as board:
        lcd = RgbLcd(board)
        ranger = Ultrasonic(board, DigitalPort.D5)

        async with asyncio.TaskGroup() as tasks:  # safe: different devices
            tasks.create_task(lcd.write_lines("scanning", "..."))
            tasks.create_task(ranger.read_distance_cm())
```

See [Concurrency model](../architecture/concurrency.md) for exactly what is
guaranteed and why.

## Handle errors

Everything the library raises derives from
[`GroveyardError`][groveyard.GroveyardError], so one `except` clause can catch
the whole library, or you can be specific:

```python
from groveyard import DeviceNotReadyError, GroveyardError, TransportError

try:
    distance = await ranger.read_distance_cm()
except DeviceNotReadyError:
    ...  # the board answered "not ready" on every retry
except TransportError:
    ...  # the bus itself failed
except GroveyardError:
    ...  # anything else the library defines
```

Out-of-range arguments (a brightness outside `0.0..1.0`, a beep of zero
seconds) are caller bugs, so they raise plain `ValueError` instead — see
[Errors](../api/errors.md).

## Test your application

You do not need a Raspberry Pi to write or run tests for code built on
groveyard — the library ships an in-memory transport and a scripted fake
firmware:

```python
from groveyard import Board, DigitalPort, Button, FakeTransport
from groveyard.testing import FakeBridgeFirmware

firmware = FakeBridgeFirmware()
firmware.digital_inputs[DigitalPort.D3] = 1


async def test_button_reads_pressed() -> None:
    async with Board(FakeTransport(responder=firmware)) as board:
        assert await Button(board, DigitalPort.D3).is_pressed()
```

See [Testing without hardware](../guides/testing.md) for the full picture,
including asserting on bus timing and concurrency.
