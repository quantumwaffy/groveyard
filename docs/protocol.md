# Hardware & Firmware Protocol Reference

This document is the single source of truth for the **wire protocol** the library
targets. It describes the physical board and its sensors as hardware facts, so a
driver author never has to reverse-engineer bytes again. It is deliberately
implementation-agnostic: it says *what the hardware expects*, not *how our Python
should be structured* (see `CLAUDE.md` for that).

> All code, comments, and docs in this project are written in **English**.

---

## 1. Topology

The board is a **GrovePi+ HAT** for the Raspberry Pi. It carries an onboard
microcontroller (AVR) that acts as an **I2C bridge**: the Raspberry Pi is the I2C
master, the board firmware is the slave, and the firmware in turn drives the
physical Grove ports (digital `D2..D8`, analog `A0..A2`, and the I2C port).

There are **two independent classes of device** on the I2C bus:

| Class | Talks to | I2C address | Example modules |
|-------|----------|-------------|-----------------|
| **Bridged** | the board firmware, which relays to a Grove port | `0x04` | button, LED, buzzer, relay, light/sound/rotary (analog), DHT, ultrasonic |
| **Native I2C** | its own controller directly on the bus | device-specific | RGB LCD (`0x3e` text, `0x62` backlight) |

Everything bridged shares the **single `0x04` endpoint**, so all bridged traffic
is serialized through one transaction channel. Native-I2C devices share the same
physical bus lines, so they are serialized by the same **bus lock** even though
they use a different address. This is the root reason the transport owns one
bus-wide lock (see `CLAUDE.md` → Concurrency model).

- **Bus number:** 1 (`/dev/i2c-1`) on all modern Pis.
- **Bridge address:** `0x04`.

---

## 2. Bridged transaction shape

Every bridged operation is the same three-step transaction and **must not be
interleaved** with any other bus traffic:

```
1. WRITE  [cmd, arg1, arg2, arg3]   # always exactly 4 bytes; pad unused args with 0
2. SLEEP  t_cmd                     # firmware needs time to service the port
3. READ   n bytes                   # only for commands that return data
```

Notes that bit people:

- **Write is always 4 bytes.** Commands that need fewer args pad with `0`.
- **The read is a separate I2C transaction**, not a repeated-start read. The
  firmware buffers the reply and hands it back on the next read.
- **First read byte is an echo** of the command id for **every** data command,
  digital read included: the firmware writes the command id ahead of the payload. Read
  `n+1` bytes and validate the echo rather than hard-coding offsets; a mismatch
  means the transaction was torn by another task and must not be decoded.
- **Write-only commands are never read back.** `pin_mode` (`5`), `digital_write`
  (`2`) and `analog_write` (`4`) queue **no** reply: the firmware's request
  handler has no branch for those command ids. A
  read issued after one of them returns the idle byte `0xFF`, which is
  indistinguishable from a not-ready sentinel and would trigger pointless
  retries. Write, wait `t_cmd`, and move on.
- **Not-ready sentinels:** a reply whose first byte is `23` (`data_not_available`)
  or `255` means "not ready yet" → wait and retry, do not treat as a value. The
  firmware answers `23` while it still owes its main loop one pass before the
  result is ready, so this is expected traffic, not a fault.
- **Retry the whole transaction, not just the read.** The firmware clears the
  pending command once it has answered, so a not-ready reply must be followed by
  a fresh `write → sleep → read`, not by another bare read.
- **Retries:** transient `OSError`/`IOError` on the bus is expected. Retry a small
  bounded number of times with a short backoff before surfacing an error.
- **Timing `t_cmd`:** ~2 ms is enough for simple digital/analog ops. Ultrasonic
  and DHT need materially longer (see their rows). Never busy-wait — this is an
  `await asyncio.sleep(...)` in our async design.

---

## 3. Bridged command table

`mode`: `1 = OUTPUT`, `0 = INPUT`. `pin` is the Grove port number (digital `2..8`,
analog `0..2`). "Returns" is the payload **after** the echo byte is stripped.

| Operation | cmd | Write args `[cmd, …]` | Read | Returns / meaning | Notes |
|-----------|----:|-----------------------|-----:|-------------------|-------|
| Firmware version | `8` | `[8, 0, 0, 0]` | 3 | `major.minor.patch` | Handshake / capability check on connect. |
| Set pin mode | `5` | `[5, pin, mode, 0]` | — | — | **No reply.** Configure once; cache the mode. |
| Digital read | `1` | `[1, pin, 0, 0]` | 1 | `0` / `1` | Button, and any digital input. Echoed like every other data command. |
| Digital write | `2` | `[2, pin, value, 0]` | — | — | **No reply.** `value` `0`/`1`. LED/buzzer/relay on–off. |
| Analog read | `3` | `[3, pin, 0, 0]` | 2 | `hi*256 + lo`, range `0..1023` | 10-bit ADC. Light/sound/rotary. |
| Analog write (PWM) | `4` | `[4, pin, value, 0]` | — | — | **No reply.** `value` `0..255` duty cycle. LED brightness. |
| Ultrasonic read | `7` | `[7, pin, 0, 0]` | 2 | distance in **cm**, `hi*256+lo` | **Needs ~50 ms** before the read. Range 3–400 cm. |
| DHT read | `40` | `[40, pin, type, 0]` | 8 | two `float32` LE: `[temp_C, humidity_%]` | `type`: `0` = DHT11 (blue), `1` = DHT22 (white). **Slow (~250 ms class).** Validate range; reject `NaN`. |

### DHT decoding

The 8 returned bytes are two little-endian IEEE-754 `float32` values:
`bytes[0:4] → temperature °C`, `bytes[4:8] → humidity %RH`. Sanity-gate the result
(e.g. temp in `-40..80 °C`, humidity in `0..100 %`); out-of-range or `NaN` means a
failed read and should be retried, not returned.

---

## 4. Native-I2C device: RGB LCD

The 16×2 RGB-backlight LCD is **two controllers at two addresses** on the same bus:

- **Text/HD44780 controller** — address `0x3e`.
  - Command: `write_byte_data(0x3e, 0x80, cmd)`.
  - Data (one character): `write_byte_data(0x3e, 0x40, ord(char))`.
  - Useful commands: `0x01` clear, `0x02` return-home, `0x08|0x04` display-on/no-cursor,
    `0x28` two-line mode, `0xC0` move to start of second line,
    `0x40 | (slot << 3)` select CGRAM slot for a custom glyph (slots `0..7`).
  - After `clear`/`home` the controller needs a short settle (~50 ms) before more writes.
- **RGB backlight controller** — address `0x62`.
  - Init once: write `0x00→reg0`, `0x00→reg1`, `0xAA→reg0x08`.
  - Set color: `R→reg4`, `G→reg3`, `B→reg2` (each `0..255`).

Because it does not go through `0x04`, the LCD driver uses the **same transport /
bus lock** but a different address and register semantics. Keep its command
constants in the driver, not in the bridge protocol layer.

---

## 5. Device-level conversions (analog modules)

The bridge only returns raw ADC counts (`0..1023`). Human-meaningful units are a
**driver responsibility**. Reference formulas for the starter-kit analog modules:

- **Rotary angle / linear potentiometer** (300° travel, 10 kΩ):
  `voltage = adc * Vref / 1023`; `degrees = voltage * 300 / Vcc` (with `Vref = Vcc = 5 V`).
  Expose a normalized `0.0..1.0` position and/or `degrees`.
- **Light sensor** (LM358): report raw counts and, optionally, the sensor
  resistance `R = (1023 - adc) * 10 / adc` (kΩ) — higher resistance ≈ darker.
- **Sound sensor**: analog envelope level; expose raw counts. Callers threshold it.
  A short averaging window smooths the inherently noisy signal.

Keep the raw value reachable on every analog driver; conversions are convenience
on top, never a replacement.

---

## 6. Starter-kit module catalog

| Module | Port kind | Primitive(s) | State the driver owns |
|--------|-----------|--------------|-----------------------|
| Button | digital in | `pinMode`, `digitalRead` | configured mode |
| Light sensor | analog in | `pinMode`, `analogRead` | configured mode |
| Sound sensor | analog in | `pinMode`, `analogRead` | configured mode, averaging window |
| Rotary / linear potentiometer | analog in | `pinMode`, `analogRead` | configured mode |
| LED (R/G/B) | digital / PWM out | `pinMode`, `digitalWrite` / `analogWrite` | on/off + brightness |
| Buzzer | digital out | `pinMode`, `digitalWrite` | on/off |
| Relay | digital out | `pinMode`, `digitalWrite` | on/off (fail-safe to off) |
| DHT temp/humidity | digital special | `dht` | sensor variant, last reading |
| Ultrasonic ranger | digital special | `ultrasonic` | last distance |
| RGB LCD | native I2C | direct register writes | text buffer, backlight color |

"State the driver owns" is exactly what the **per-device lock** protects against
concurrent tasks (see `CLAUDE.md`).