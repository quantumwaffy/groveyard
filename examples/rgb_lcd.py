"""Write text and cycle the backlight colour on the Grove RGB LCD.

Wiring: the LCD is native I2C, plugged into the board's I2C port — there is
no digital/analog PORT to configure, and only one can be attached at a time.

Run:
    python examples/rgb_lcd.py
"""

import asyncio

from groveyard import Board, RgbLcd

COLORS = [
    (255, 0, 0),  # red
    (0, 255, 0),  # green
    (0, 0, 255),  # blue
    (255, 255, 255),  # white
]


async def main() -> None:
    async with Board.on_i2c() as board, RgbLcd(board) as lcd:
        print("Writing text...")
        await lcd.write_lines("hello, groveyard", "from a real Pi!")
        await asyncio.sleep(1)

        for red, green, blue in COLORS:
            print(f"Backlight -> ({red}, {green}, {blue})")
            await lcd.set_color(red, green, blue)
            await asyncio.sleep(1)

        print("Clearing the display...")
        await lcd.clear()

        print("Done. Display will be cleared and dark on exit.")


if __name__ == "__main__":
    asyncio.run(main())
