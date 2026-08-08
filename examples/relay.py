"""Switch a Grove relay on and off.

Wiring: plug the relay into digital port D6 (or change PORT below). Nothing
dangerous is switched by default here — attach a low-voltage load (an LED
strip, a small fan) if you want to see the effect, not mains power.

Run:
    python examples/relay.py
"""

import asyncio

from groveyard import Board, DigitalPort, Relay

PORT = DigitalPort.D6


async def main() -> None:
    async with Board.on_i2c() as board, Relay(board, PORT) as relay:
        print("Closing the circuit (energised)...")
        await relay.close_circuit()
        print(f"is_closed_circuit: {relay.is_closed_circuit}")
        await asyncio.sleep(2)

        print("Opening the circuit (de-energised)...")
        await relay.open_circuit()
        print(f"is_closed_circuit: {relay.is_closed_circuit}")

        print("Done. Relay will be de-energised on exit.")


if __name__ == "__main__":
    asyncio.run(main())
