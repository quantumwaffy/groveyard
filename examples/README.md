# Examples

Small, standalone scripts that talk to **real hardware** — a GrovePi+ HAT on
a Raspberry Pi. Unlike the test suite (which runs entirely against the
in-memory `FakeTransport`, see [Testing without hardware](https://quantumwaffy.github.io/groveyard/guides/testing/)),
every script here uses `Board.on_i2c()` and needs an actual board and the
actual Grove module plugged in.

> [!WARNING]
> These examples are exactly what the README's real-hardware warning is
> about: the library has not yet been confirmed against physical hardware.
> Running these is how that gets confirmed — please
> [open an issue](https://github.com/quantumwaffy/groveyard/issues) with
> what you see, good or bad.

## Setup

```bash
pip install groveyard[hardware]   # adds smbus2, needed for real I2C
```

Make sure I2C is enabled (`sudo raspi-config` → *Interface Options* → *I2C*)
and your user is in the `i2c` group — see
[Installation](https://quantumwaffy.github.io/groveyard/getting-started/installation/).

## Wiring

Each script has a `PORT` constant near the top — edit it if you wired the
module to a different socket than the default below.

| Script | Module | Default port                         |
|---|---|--------------------------------------|
| `board.py` | — (just the HAT itself) | —                                    |
| `button.py` | Button | `D3`                                 |
| `buzzer.py` | Buzzer | `D4`                                 |
| `led.py` | LED | `D5`                                 |
| `relay.py` | Relay | `D6`                                 |
| `light_sensor.py` | Light sensor | `A0`                                 |
| `sound_sensor.py` | Sound sensor | `A1`                                 |
| `potentiometer.py` | Rotary angle sensor | `A2`                                 |
| `dht.py` | DHT temp/humidity sensor | `D7`                                 |
| `ultrasonic.py` | Ultrasonic ranger | `D8`                                 |
| `rgb_lcd.py` | RGB LCD | I2C port (no `PORT` constant needed) |

You can plug in and run just the ones you have — they are independent of
each other.

## Running

```bash
python examples/board.py
python examples/led.py
# ...
```

Each script prints what it is doing and exits on its own; nothing runs in a
loop forever. Press `Ctrl-C` at any point — actuators (LED, buzzer, relay)
are driven back to *off* on exit either way, even on an error or a
keyboard interrupt, because `Board`/`Device` are used as async context
managers.
