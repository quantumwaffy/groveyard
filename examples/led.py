"""Drive a Grove LED: on/off, then a brightness fade.

Wiring: plug the LED into digital port D5 (or change PORT below). D5 is
PWM-capable, which the fade below relies on — full brightness fading only
works on a PWM-capable socket (D3, D5, D6 on most GrovePi+ boards); on other
digital sockets `set_brightness` still works, it is just effectively on/off.

Run:
    python examples/led.py
"""

import asyncio

from groveyard import Board, DigitalPort, Led

PORT = DigitalPort.D5


async def main() -> None:
    async with Board.on_i2c() as board, Led(board, PORT) as led:
        print("Switching on...")
        await led.on()
        await asyncio.sleep(1)

        print("Switching off...")
        await led.off()
        await asyncio.sleep(1)

        print("Fading 0% -> 100% brightness...")
        for step in range(0, 11):
            value = step / 10
            await led.set_brightness(value)
            print(f"brightness = {value:.1f}")
            await asyncio.sleep(0.2)

        print("Done. LED will be switched off on exit.")


if __name__ == "__main__":
    asyncio.run(main())
