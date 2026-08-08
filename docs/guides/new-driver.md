# Writing a new driver

A worked example: adding a Grove **soil moisture sensor** — a plain analog
input, mechanically identical to [`LightSensor`][groveyard.LightSensor],
which is a good real driver to keep open in a second tab while reading this.

## 1. Find the module in the wire protocol

Every driver is built from facts in [Wire protocol](../protocol.md), never
guessed. A soil moisture sensor is just an analog input — it needs no new
row in the command table, only an entry in
[§6, the module catalog](../protocol.md#6-starter-kit-module-catalog):
`pinMode`, `analogRead`, state: configured mode. If your module *did* need a
new command, that byte-level work belongs in
[`groveyard/protocol/commands.py`][groveyard.protocol.commands] and
[`groveyard/protocol/bridge.py`][groveyard.protocol.bridge.BridgeProtocol] — the device layer
never spells out raw command ids.

## 2. Pick the closest base class

| Your module reads/writes | Base class |
|---|---|
| A single on/off level | [`DigitalInputDevice`][groveyard.DigitalInputDevice] |
| A single on/off output | [`DigitalOutputDevice`][groveyard.DigitalOutputDevice] |
| A 10-bit ADC value | [`AnalogInputDevice`][groveyard.AnalogInputDevice] |
| Something bridged but "special" (its own command, like DHT or the ultrasonic ranger) | [`BridgedDevice[DigitalPort]`][groveyard.BridgedDevice] directly |
| Its own controller on the bus, not through the bridge | [`I2CDevice`][groveyard.I2CDevice] |

A soil moisture sensor is an analog input, so:

```python
from groveyard.devices.base import AnalogInputDevice


class SoilMoistureSensor(AnalogInputDevice): ...
```

That one line already gives you `read_raw()` (`0..1023`) and `read_ratio()`
(`0.0..1.0`), a claimed port, a device lock, and safe close/cleanup — see
[Layers overview § the device layer](../architecture/index.md#the-device-layer)
for what each base contributes.

## 3. Add only what the base does not give you

Most drivers add one or two conversions on top of the raw reading. Name every
constant, cite the formula's source, and never make the raw value
unreachable:

```python
"""Driver for the Grove capacitive soil moisture sensor.

A plain analog input (``docs/protocol.md`` section 6): drier soil reads a
*higher* resistance and therefore a *lower* raw count. There is no official
calibration table, so this driver exposes the reading as a percentage of full
scale rather than inventing a physical unit.
"""

from __future__ import annotations

from typing import Final

from groveyard.devices.base import AnalogInputDevice
from groveyard.protocol.commands import ADC_MAX_COUNTS

DRY_SOIL_COUNTS: Final[int] = 300
"""Raw reading in open air — the sensor's practical zero point."""

SATURATED_SOIL_COUNTS: Final[int] = 700
"""Raw reading fully submerged in water — the sensor's practical full scale."""


class SoilMoistureSensor(AnalogInputDevice):
    """A Grove capacitive soil moisture sensor on an analog socket.

    Inherits :meth:`~groveyard.devices.base.AnalogInputDevice.read_raw` and
    :meth:`~groveyard.devices.base.AnalogInputDevice.read_ratio`; the raw
    ``0..1023`` reading always stays reachable.
    """

    async def read_moisture_percent(self) -> float:
        """Read soil moisture as a percentage of the sensor's practical range.

        Returns:
            ``0.0`` at :data:`DRY_SOIL_COUNTS` or below, ``100.0`` at
            :data:`SATURATED_SOIL_COUNTS` or above, linear in between.

        Raises:
            DeviceClosedError: If the device has been closed.
            NotConnectedError: If the board is not connected.
            DeviceNotReadyError: If the board never became ready.
            ProtocolError: If the reply was malformed.
            TransportError: If the bus itself failed.
        """
        async with self._lock:
            counts = await self._read_raw_locked()
        span = SATURATED_SOIL_COUNTS - DRY_SOIL_COUNTS
        clamped = min(max(counts, DRY_SOIL_COUNTS), SATURATED_SOIL_COUNTS)
        return (clamped - DRY_SOIL_COUNTS) / span * 100.0
```

!!! danger "The locking rule, worth repeating"
    A **public** method acquires `self._lock` and delegates to a private
    `*_locked` helper. A `*_locked` helper **never** takes the lock again —
    call `self._read_raw_locked()`, not `self.read_raw()`, from inside one.
    `asyncio.Lock` is not reentrant; getting this backwards deadlocks the
    task against itself. See
    [Concurrency model](../architecture/concurrency.md#the-_locked-convention).

    Above, the conversion math runs *outside* the lock on purpose — it is
    pure and touches no shared state, so there is no reason to hold the
    critical section open for it. Only the bus-touching part needs the lock.

## 4. Wire it into the public API

Add the class to `src/groveyard/devices/__init__.py` and re-export it from
`src/groveyard/__init__.py`, alphabetically in both `__all__` lists. This is
the *only* place another layer changes — nothing in `board.py` or
`transport/` needs to know your driver exists (Open/Closed Principle).

## 5. Write tests against the fake

No hardware is involved — see
[Testing without hardware](testing.md) for the full pattern set. At minimum,
cover:

- the happy path and the exact conversion math (`pytest.approx`);
- boundary values (here: `0`, `1023`, and both sides of the clamp);
- the pin mode being configured once, not on every read;
- the concurrency contract — many tasks on *this* sensor serialise
  (`transport.has_interleaved_sessions()` stays `False`), tasks on a
  *different* device are not blocked by it;
- cancellation mid-read leaves the device usable afterwards.

```python
async def test_moisture_follows_the_clamped_linear_formula(board, firmware):
    firmware.analog_inputs[AnalogPort.A0] = 500
    sensor = SoilMoistureSensor(board, AnalogPort.A0)
    assert await sensor.read_moisture_percent() == pytest.approx(50.0)
```

## 6. Run the gates

```bash
uv run ruff check . && uv run ruff format .
uv run ty check
uv run pytest
```

All four must be clean before a driver is considered done — see
[Contributing](../contributing.md#the-gates).

## Using the orchestrated workflow instead

If you are working with Claude Code in this repository, `/new-driver <module>`
runs steps 1–6 through the `driver-author` and `async-reviewer` subagents
automatically, following exactly this process — see the
[`Orchestration`](https://github.com/quantumwaffy/groveyard/blob/master/CLAUDE.md#orchestration--how-work-is-distributed)
section of `CLAUDE.md`.
