"""Read temperature and humidity from a Grove DHT sensor.

Wiring: plug the sensor into digital port D7 (or change PORT below). The
blue module in the starter kit is a DHT11 (the default); switch VARIANT to
DhtVariant.DHT22 if you have the white one.

Run:
    python examples/dht.py
"""

import asyncio

from groveyard import Board, Dht, DhtVariant, DigitalPort

PORT = DigitalPort.D7
VARIANT = DhtVariant.DHT11


async def main() -> None:
    async with Board.on_i2c() as board, Dht(board, PORT, VARIANT) as sensor:
        print(f"Reading {PORT.name} ({VARIANT.name}) five times, a couple of seconds apart.")
        for _ in range(5):
            reading = await sensor.read()
            print(
                f"temperature={reading.temperature_celsius:.1f} C "
                f"({reading.temperature_fahrenheit:.1f} F)  "
                f"humidity={reading.humidity_percent:.1f} %"
            )
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
