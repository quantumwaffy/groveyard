"""Read a Grove rotary angle sensor: raw counts, voltage, and degrees.

Wiring: plug the rotary sensor into analog port A2 (or change PORT below).
Turn the knob partway through the run to see the readings change.

Run:
    python examples/potentiometer.py
"""

import asyncio

from groveyard import AnalogPort, Board, Potentiometer

PORT = AnalogPort.A2


async def main() -> None:
    async with Board.on_i2c() as board, Potentiometer(board, PORT) as knob:
        print(f"Reading {PORT.name} for 10 seconds — try turning the knob.")
        for _ in range(10):
            raw = await knob.read_raw()
            volts = await knob.read_voltage()
            degrees = await knob.read_degrees()
            print(f"raw={raw:4d}  voltage={volts:.2f} V  angle={degrees:.1f} deg")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
