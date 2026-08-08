"""Sound a Grove buzzer: on/off, then a few short beeps.

Wiring: plug the buzzer into digital port D5 (or change PORT below).

Run:
    python examples/buzzer.py
"""

import asyncio

from groveyard import Board, Buzzer, DigitalPort

PORT = DigitalPort.D5


async def main() -> None:
    async with Board.on_i2c() as board, Buzzer(board, PORT) as buzzer:
        print("Switching on for 1 second...")
        await buzzer.on()
        await asyncio.sleep(1)
        await buzzer.off()

        print("Three short beeps...")
        for _ in range(3):
            await buzzer.beep(0.2)
            await asyncio.sleep(0.3)

        print("Done. Buzzer will be silenced on exit.")


if __name__ == "__main__":
    asyncio.run(main())
