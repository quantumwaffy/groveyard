"""A traffic light with a pedestrian crossing: LEDs, a buzzer, and the LCD as one scene.

The interesting part is *when* things run concurrently and when they don't.
Text and colour on the LCD, and each LED's own state, are always awaited one
after another — updating one device is a single logical operation, and two
calls on the *same* device would just queue behind its lock anyway. But
fading the green LED out while the buzzer counts down is two *different*
devices, so it runs as a real `asyncio.TaskGroup`: no manual coordination
needed, only the bus itself briefly serialises the two transactions.

Wiring: red on D3, yellow on D5, green on D6 — the three PWM-capable sockets,
which is what lets yellow fade in and green fade out instead of just
switching. Buzzer on D4. RGB LCD on the I2C port. Change the PORT constants
below if you wired it differently.

Run:
    python examples/traffic_light.py
"""

import asyncio

from groveyard import Board, Buzzer, DigitalPort, Led, RgbLcd

RED_PORT = DigitalPort.D3
YELLOW_PORT = DigitalPort.D5
GREEN_PORT = DigitalPort.D6
BUZZER_PORT = DigitalPort.D4

CYCLES = 2


async def show(lcd: RgbLcd, first: str, second: str, color: tuple[int, int, int]) -> None:
    """Put the LCD into one named state: two lines of text plus a matching backlight."""
    await lcd.write_lines(first, second)
    await lcd.set_color(*color)


async def fade(led: Led, *, start: float, stop: float, seconds: float) -> None:
    """Ramp a PWM-capable LED's brightness from `start` to `stop` over `seconds`."""
    steps = 10
    for i in range(steps + 1):
        value = start + (stop - start) * i / steps
        await led.set_brightness(value)
        await asyncio.sleep(seconds / steps)


async def warn_and_fade(green: Led, buzzer: Buzzer) -> None:
    """Fade the green LED out while the buzzer counts down — different devices, one TaskGroup."""
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(fade(green, start=1.0, stop=0.0, seconds=1.2))
        tasks.create_task(_warning_beeps(buzzer))


async def _warning_beeps(buzzer: Buzzer) -> None:
    for _ in range(3):
        await buzzer.beep(0.1)
        await asyncio.sleep(0.3)


async def main() -> None:
    async with (
        Board.on_i2c() as board,
        Led(board, RED_PORT) as red,
        Led(board, YELLOW_PORT) as yellow,
        Led(board, GREEN_PORT) as green,
        Buzzer(board, BUZZER_PORT) as buzzer,
        RgbLcd(board) as lcd,
    ):
        for cycle in range(1, CYCLES + 1):
            print(f"--- cycle {cycle}/{CYCLES} ---")

            print("RED: stop.")
            await red.on()
            await show(lcd, "STOP", "wait...", (255, 0, 0))
            await asyncio.sleep(2)

            print("RED + YELLOW: get ready (yellow fades in).")
            await show(lcd, "READY", "get set", (255, 140, 0))
            await fade(yellow, start=0.0, stop=1.0, seconds=1.0)
            await asyncio.sleep(0.5)

            print("GREEN: go.")
            await red.off()
            await yellow.off()
            await green.on()
            await show(lcd, "GO", "cross now", (0, 255, 0))
            await asyncio.sleep(2)

            print("Green fading out + buzzer counting down, concurrently.")
            await warn_and_fade(green, buzzer)

            print("YELLOW: caution.")
            await green.off()
            await yellow.on()
            await show(lcd, "CAUTION", "clear now", (255, 140, 0))
            await asyncio.sleep(1)
            await yellow.off()

        print("Done. Every LED, the buzzer, and the LCD will reset on exit.")


if __name__ == "__main__":
    asyncio.run(main())
