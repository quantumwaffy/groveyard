"""Read a Grove button.

Wiring: plug the button into digital port D3 (or change PORT below).

Run:
    python examples/button.py
Then press the button a few times within the next 10 seconds.
"""

import asyncio

from groveyard import Board, Button, DigitalPort

PORT = DigitalPort.D3


async def main() -> None:
    async with Board.on_i2c() as board, Button(board, PORT) as button:
        print(f"Watching {PORT.name} for 10 seconds — press the button.")
        for _ in range(20):
            state = "PRESSED" if await button.is_pressed() else "released"
            print(state)
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
