# groveyard

A modern, fully typed **async** Python library for the sensors and actuators of a
GrovePi+ starter kit on a Raspberry Pi.

Many concurrent tasks can share one I2C bus and one stateful device without
stepping on each other: the bus is serialised by a single lock, and each device
owns a second lock that makes a multi-step operation atomic. Nothing blocks the
event loop.

```python
import asyncio

from groveyard import AnalogPort, Board, DigitalPort, Led, LightSensor


async def main() -> None:
    async with Board.on_i2c() as board:
        sensor = LightSensor(board, AnalogPort.A0)
        led = Led(board, DigitalPort.D4)

        if await sensor.read_raw() < 300:
            await led.set_brightness(0.6)


asyncio.run(main())
```

## Install

```bash
pip install groveyard            # develop and test anywhere
pip install groveyard[hardware]  # on the Pi: adds smbus2
```

Python 3.12+. `smbus2` is the only runtime dependency, and only on the Pi — it
lives behind the transport abstraction, so nothing imports it off-device.

## Supported modules

| Class | Port | Highlights |
|---|---|---|
| `Button` | digital in | `is_pressed()` |
| `LightSensor` | analog in | raw counts, ratio, `read_resistance_kohm()` |
| `SoundSensor` | analog in | raw counts plus an averaging window |
| `Potentiometer` | analog in | ratio, `read_voltage()`, `read_degrees()` |
| `Led` | digital / PWM out | on/off plus `set_brightness(0.0..1.0)` |
| `Buzzer` | digital out | on/off plus cancellation-safe `beep(seconds)` |
| `Relay` | digital out | `close_circuit()` / `open_circuit()`, fail-safe |
| `Dht` | digital special | `DhtReading(temperature_celsius, humidity_percent)` |
| `Ultrasonic` | digital special | distance in cm, `None` when nothing is in range |
| `RgbLcd` | native I2C | 16×2 text plus RGB backlight |

Every analog driver keeps the raw `0..1023` reading reachable; unit conversions
are convenience on top, never a replacement.

## Concurrency

Two hazards, two locks:

* **The bus is shared.** A bridged operation is `write → sleep → read`; if two
  tasks interleave, one reads the other's reply. The transport wraps the whole
  transaction in one `asyncio.Lock`, so every exchange — bridged or native-I2C —
  is atomic with respect to every other.
* **Devices are stateful.** One logical operation can span several transactions
  (configure-then-read, a read-modify-write on the LCD or a dimmable LED). Each
  driver owns an `asyncio.Lock` that makes that operation atomic. Two tasks on
  *different* devices proceed concurrently, contending only briefly on the bus.

Locks are always taken in the order **device → bus**, they are always taken with
`async with` (so cancellation cannot leak one), and actuators fail safe to *off*
when they are closed or the board disconnects.

```python
async with Board.on_i2c() as board:
    lcd = RgbLcd(board)
    ranger = Ultrasonic(board, DigitalPort.D5)
    async with asyncio.TaskGroup() as tasks:  # safe: different devices
        tasks.create_task(lcd.write_lines("scanning", "..."))
        tasks.create_task(ranger.read_distance_cm())
```

Two drivers may not claim the same socket — the second one raises
`PortInUseError` instead of silently corrupting the first one's cached state.

## Testing without a Raspberry Pi

The library ships its own test doubles, so applications can be tested in CI:

```python
from groveyard import Board, DigitalPort, Button, FakeTransport
from groveyard.testing import FakeBridgeFirmware

firmware = FakeBridgeFirmware()
firmware.digital_inputs[DigitalPort.D3] = 1

async with Board(FakeTransport(responder=firmware)) as board:
    assert await Button(board, DigitalPort.D3).is_pressed()
```

The fake records every bus event with the id of the transaction it belongs to,
and records requested delays instead of sleeping — so timing and atomicity are
asserted, not waited for.

## Errors

Everything derives from `GroveyardError`: `TransportError` (the bus failed),
`ProtocolError` (malformed reply), `DeviceNotReadyError` (the board answered
"not ready" on every attempt), `BoardError` (`NotConnectedError`,
`PortInUseError`) and `DeviceError` (`DeviceClosedError`). Out-of-range
arguments are caller bugs and raise plain `ValueError`.

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format .
uv run ty check
uv run pytest
```

The wire protocol is documented in [`docs/protocol.md`](docs/protocol.md);
architecture and conventions live in [`CLAUDE.md`](CLAUDE.md).

## Licence

MIT.
