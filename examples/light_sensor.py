"""Read a Grove light sensor: raw counts, ratio, and resistance.

Wiring: plug the light sensor into analog port A0 (or change PORT below).
Cover it with your hand partway through the run to see the readings change.

Run:
    python examples/light_sensor.py
"""

import asyncio

from groveyard import AnalogPort, Board, LightSensor

PORT = AnalogPort.A0


async def main() -> None:
    async with Board.on_i2c() as board, LightSensor(board, PORT) as sensor:
        print(f"Reading {PORT.name} for 10 seconds — try covering the sensor.")
        for _ in range(10):
            raw = await sensor.read_raw()
            ratio = await sensor.read_ratio()
            kohm = await sensor.read_resistance_kohm()
            print(f"raw={raw:4d}  ratio={ratio:.3f}  resistance={kohm:.2f} kOhm")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
