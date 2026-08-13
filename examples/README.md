# Examples

Small, standalone scripts that talk to **real hardware** — a GrovePi+ HAT on
a Raspberry Pi. Unlike the test suite (which runs entirely against the
in-memory `FakeTransport`, see [Testing without hardware](https://quantumwaffy.github.io/groveyard/guides/testing/)),
every script here uses `Board.on_i2c()` and needs an actual board and the
actual Grove module plugged in.

> [!NOTE]
> Every script here has been run end to end against a physical GrovePi+
> board — see the README's real-hardware note. If you hit anything
> unexpected on your own board, please
> [open an issue](https://github.com/quantumwaffy/groveyard/issues) with
> what you see.

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

## Combined scenes

Unlike the scripts above, these need several modules wired in *at once* —
they exist to show devices working together as one scene, not to exercise
one module in isolation.

| Script | Modules needed | Ports |
|---|---|---|
| `traffic_light.py` | 3× LED, Buzzer, RGB LCD | red `D3`, yellow `D5`, green `D6`, buzzer `D4`, LCD on the I2C port |

`traffic_light.py` runs a red/yellow/green cycle with a pedestrian crossing
on the LCD, and doubles as a live demo of the concurrency model: fading the
green LED out while the buzzer counts down is two different devices running
as one `asyncio.TaskGroup`, with no manual coordination needed between them.
