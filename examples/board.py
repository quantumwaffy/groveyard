"""Connect to the GrovePi+ HAT itself — no Grove module required.

Confirms the bus opens, the firmware-version handshake succeeds, and the
board disconnects cleanly. Good first thing to run on a fresh Pi before
plugging anything in: if this doesn't work, nothing else will either.

Run:
    python examples/board.py
"""

import asyncio

from groveyard import Board


async def main() -> None:
    print("Connecting to the GrovePi+ HAT on /dev/i2c-1 ...")
    async with Board.on_i2c() as board:
        print(f"Connected. Firmware version: {board.firmware_version}")
        print(f"is_connected: {board.is_connected}")
    print("Disconnected cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
