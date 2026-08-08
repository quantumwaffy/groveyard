"""Read a Grove sound sensor: raw counts and an averaged reading.

Wiring: plug the sound sensor into analog port A1 (or change PORT below).
Clap or talk near it partway through the run to see the readings jump.

Run:
    python examples/sound_sensor.py
"""

import asyncio

from groveyard import AnalogPort, Board, SoundSensor

PORT = AnalogPort.A1


async def main() -> None:
    async with Board.on_i2c() as board, SoundSensor(board, PORT) as sensor:
        print(f"Reading {PORT.name} for 10 seconds — try clapping near it.")
        for _ in range(10):
            raw = await sensor.read_raw()
            average = await sensor.read_average()
            print(f"raw={raw:4d}  average(window={sensor.window_size})={average:.1f}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
