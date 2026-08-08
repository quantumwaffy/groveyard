# Testing without hardware

Every guarantee in [Concurrency model](../architecture/concurrency.md) is
regression-tested against an in-memory transport — not just inside groveyard
itself, but for any application built on top of it. This page shows the
patterns the library's own test suite uses, so you can reuse them.

## The two building blocks

[`FakeTransport`][groveyard.FakeTransport] implements the same
[`Transport`][groveyard.Transport] interface as
[`SMBusTransport`][groveyard.SMBusTransport] — that is the Liskov
substitution principle at work: nothing above the transport layer can tell
the difference. [`FakeBridgeFirmware`][groveyard.testing.FakeBridgeFirmware]
plugs into it as a [`BusResponder`][groveyard.transport.fake.BusResponder]
and answers bridged commands the way the real `0x04` firmware does: it
echoes the command id, packs multi-byte payloads, and can be told to answer
"not ready" a bounded number of times before producing a value.

```python
from groveyard import Board, DigitalPort, FakeTransport
from groveyard.testing import FakeBridgeFirmware

firmware = FakeBridgeFirmware()
firmware.digital_inputs[DigitalPort.D3] = 1  # describe the physical world

async with Board(FakeTransport(responder=firmware)) as board:
    ...
```

`firmware` exposes one dict per input/output kind — `digital_inputs`,
`analog_inputs`, `ultrasonic_distances`, `dht_readings` — plus
`digital_outputs`, `pwm_outputs` and `pin_modes` to inspect what a driver
*wrote*, and `commands`: every four-byte frame received, in order. See the
[testing API reference][groveyard.testing.FakeBridgeFirmware] for the full
list.

!!! tip "pytest fixtures"
    groveyard's own test suite wires these into three fixtures —
    `firmware`, `transport`, `board` — in `tests/conftest.py`. Copying that
    file (or the equivalent three lines) into your application's `conftest.py`
    is the fastest way to start.

## Asserting what was sent

`tests/frames.py`'s `CommandLog` is a small, reusable pattern worth copying
into your own test suite once you have more than one or two assertions on raw
frames:

```python
class CommandLog:
    def __init__(self, firmware: FakeBridgeFirmware) -> None:
        self._firmware = firmware

    def frames(self, command: BridgeCommand, port: Port) -> list[bytes]:
        return [f for f in self._firmware.commands if f[0] == int(command) and f[1] == int(port)]

    def digital_writes(self, port: Port) -> list[int]:
        return [f[2] for f in self.frames(BridgeCommand.DIGITAL_WRITE, port)]
```

```python
log = CommandLog(firmware)
await led.on()
assert log.digital_writes(DigitalPort.D4) == [DIGITAL_HIGH]
```

## Asserting on timing

[`FakeSession.settle()`][groveyard.transport.fake.FakeSession.settle] and
[`FakeTransport.wait()`][groveyard.FakeTransport.wait] **record** the delay
they were asked for instead of actually sleeping — so a test can assert that
the documented timing was requested without paying for it in wall-clock time:

```python
await ultrasonic.read_distance_cm()
assert ULTRASONIC_SETTLE_SECONDS in transport.delays
```

This is why the whole suite (170+ tests as of this writing) runs in about a
second.

## Asserting bus transactions never interleave

[`FakeTransport.has_interleaved_sessions()`][groveyard.FakeTransport.has_interleaved_sessions]
checks that every recorded transaction's events are contiguous in the event
log — exactly what the bus lock is supposed to guarantee:

```python
async with asyncio.TaskGroup() as tasks:
    tasks.create_task(led.set_brightness(0.6))
    tasks.create_task(ranger.read_distance_cm())

assert not transport.has_interleaved_sessions()
```

!!! warning "The fake must suspend, or this proves nothing"
    `FakeSession` deliberately awaits `asyncio.sleep(0)` on every bus
    operation, the same way a real transport suspends inside
    `asyncio.to_thread`. Without a genuine suspension point, an uncontended
    `asyncio.Lock` never yields to the scheduler and a whole fake transaction
    would run to completion in one step — `has_interleaved_sessions()` could
    never observe an interleaving even with the bus lock removed entirely.
    This was found and fixed by an async-concurrency review; see
    [Concurrency model](../architecture/concurrency.md#regression-testing-a-concurrency-guarantee).

## Testing a driver's concurrency contract

To prove that two tasks on the *same* device genuinely serialise (not just
that the bus doesn't interleave, but that the device lock is actually being
taken), interrupt a task mid-operation deterministically by polling the event
log instead of guessing how many scheduler turns a code path takes:

```python
async def wait_for_events(transport: FakeTransport, count: int) -> None:
    for _ in range(1000):
        if len(transport.events) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"only {len(transport.events)} events, expected {count}")


async def test_a_cancelled_dim_leaves_the_led_usable(board, transport):
    led = Led(board, DigitalPort.D4)
    marker = len(transport.events)

    task = asyncio.create_task(led.set_brightness(0.6))
    await wait_for_events(transport, marker + 1)  # interrupt mid-transaction
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await led.set_brightness(0.3)  # the device lock was released
    assert led.brightness == 0.3
```

For "does the device lock actually serialise these two calls", a
`Board` subclass that counts in-flight calls across an `await asyncio.sleep(0)`
is the pattern the DHT and ultrasonic test suites use — without a device
lock, a second task would enter at that yield point:

```python
class TrackingBoard(Board):
    def __init__(self, transport):
        super().__init__(transport)
        self.max_in_flight = 0
        self._in_flight = 0

    async def dht_read(self, port, variant):
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            await asyncio.sleep(0)
            return await super().dht_read(port, variant)
        finally:
            self._in_flight -= 1
```

## Scripting a reply directly

When you need one specific, otherwise-unreachable reply — a malformed echo
byte, a `NaN` DHT frame — script it directly rather than going through the
firmware's physical-world model:

```python
transport.queue_reply(bytes([BridgeCommand.DIGITAL_READ + 1, 1]))  # wrong echo byte
with pytest.raises(ProtocolError):
    await board.digital_read(DigitalPort.D2)
```

Queued replies are consumed first, in order; once the queue is empty, reads
fall back to the responder.
