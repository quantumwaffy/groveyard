"""Measure distance with a Grove ultrasonic ranger.

Wiring: plug the ranger into digital port D8 (or change PORT below). Wave
your hand in front of it partway through the run.

Run:
    python examples/ultrasonic.py
"""

import asyncio

from groveyard import Board, DigitalPort, Ultrasonic

PORT = DigitalPort.D8


async def main() -> None:
    async with Board.on_i2c() as board, Ultrasonic(board, PORT) as ranger:
        print(f"Reading {PORT.name} for 10 seconds — try waving a hand in front of it.")
        for _ in range(10):
            distance = await ranger.read_distance_cm()
            if distance is None:
                print("no echo (nothing in range 3-400 cm)")
            else:
                print(f"distance={distance} cm")
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
