---
title: groveyard
description: A modern, fully typed async Python library for GrovePi+ sensors and actuators.
---

# groveyard

**A modern, fully typed `asyncio` library for the sensors and actuators of a
GrovePi+ starter kit on a Raspberry Pi.**

Many concurrent tasks can safely share one I2C bus and one stateful device.
Nothing blocks the event loop. Every public surface is typed and documented.

```python
import asyncio

from groveyard import AnalogPort, Board, DigitalPort, Led, LightSensor


async def main() -> None:
    async with Board.on_i2c() as board:
        sensor = LightSensor(board, AnalogPort.A0)
        led = Led(board, DigitalPort.D5)

        if await sensor.read_raw() < 300:
            await led.set_brightness(0.6)


asyncio.run(main())
```

<div class="grid cards" markdown>

-   :material-lock-outline:{ .lg .middle } **Two locks, no races**

    ---

    A single bus lock serialises every I2C transaction; a per-device lock
    makes each multi-step operation atomic. Cancellation never leaks either
    one.

    [:octicons-arrow-right-24: Concurrency model](architecture/concurrency.md)

-   :material-layers-triple-outline:{ .lg .middle } **Clean layering**

    ---

    Transport → protocol → board → drivers → public API. Each layer depends
    only on the one below it, so adding a module never means editing a core
    layer.

    [:octicons-arrow-right-24: Layers overview](architecture/index.md)

-   :material-raspberry-pi:{ .lg .middle } **No Pi required to develop**

    ---

    An in-memory fake transport and a scripted fake firmware ship with the
    library, so your application's tests never need real hardware.

    [:octicons-arrow-right-24: Testing without hardware](guides/testing.md)

-   :material-shield-check-outline:{ .lg .middle } **Fully typed, fail-safe**

    ---

    Every function is annotated and `ty`-clean. Actuators default to *off*
    and drive themselves back there on close, disconnect, or a crash.

    [:octicons-arrow-right-24: API reference](api/index.md)

</div>

## Supported modules

| Class | Port | Highlights |
|---|---|---|
| [`Button`][groveyard.Button] | digital in | `is_pressed()` |
| [`LightSensor`][groveyard.LightSensor] | analog in | raw counts, ratio, `read_resistance_kohm()` |
| [`SoundSensor`][groveyard.SoundSensor] | analog in | raw counts plus an averaging window |
| [`Potentiometer`][groveyard.Potentiometer] | analog in | ratio, `read_voltage()`, `read_degrees()` |
| [`Led`][groveyard.Led] | digital / PWM out | on/off plus `set_brightness(0.0..1.0)` |
| [`Buzzer`][groveyard.Buzzer] | digital out | on/off plus cancellation-safe `beep(seconds)` |
| [`Relay`][groveyard.Relay] | digital out | `close_circuit()` / `open_circuit()`, fail-safe |
| [`Dht`][groveyard.Dht] | digital special | `DhtReading(temperature_celsius, humidity_percent)` |
| [`Ultrasonic`][groveyard.Ultrasonic] | digital special | distance in cm, `None` when nothing is in range |
| [`RgbLcd`][groveyard.RgbLcd] | I2C port | 16×2 text plus RGB backlight |

Every analog driver keeps the raw `0..1023` reading reachable; unit
conversions are convenience on top, never a replacement.

## Where to go next

- New to the library? Start with [Installation](getting-started/installation.md)
  and the [Quickstart](getting-started/quickstart.md).
- Want to understand *why* it is built this way? Read the
  [layers overview](architecture/index.md) and the
  [concurrency model](architecture/concurrency.md) — the two things worth
  understanding before you touch the code.
- Want to add a driver or fix a bug? [Contributing](contributing.md) walks
  through the whole loop, including a worked example of adding a new module.
- Curious about the exact bytes on the wire? [Wire protocol](protocol.md)
  documents the `0x04` bridge command set this library targets.

## Design principles

- **Explicit over implicit.** No hidden global state, no monkeypatching, no
  magic numbers — every constant is named and cited against the protocol.
- **Fail safe.** Actuators default to *off*; a cancelled or crashed shutdown
  still leaves hardware in a known state (see
  [Concurrency model](architecture/concurrency.md#cancellation-safety)).
- **Dependency inversion.** Drivers depend on the `Board` abstraction, the
  board depends on the `Transport` abstraction — never the other way round,
  and never on `smbus2` directly outside `transport/i2c.py`.
- **Testable by construction.** Because I/O is behind an abstraction, any
  application built on groveyard is unit-testable without a Raspberry Pi.
