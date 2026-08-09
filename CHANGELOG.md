# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) —
while the major version is `0`, a minor bump may still include breaking
changes to the public API.

## [Unreleased]

## [0.1.2] - 2026-08-09

Initial release: the full async driver stack for a GrovePi+ starter kit,
confirmed against a physical GrovePi+ board.

### Added

- **Transport layer** — a single bus-wide `asyncio.Lock` guarding every I2C
  transaction, with two implementations: `SMBusTransport` for real hardware
  (blocking `smbus2` calls dispatched through `asyncio.to_thread`, bounded
  retries on transient `OSError`) and `FakeTransport`, an in-memory double
  that records every operation and requires no hardware.
- **Protocol layer** — `BridgeProtocol`, encoding and decoding the `0x04`
  bridge firmware's command set: fixed-width frames, echo-byte validation,
  `23`/`255` not-ready sentinels with bounded whole-transaction retries
  (including a per-command validation hook used to retry an implausible DHT
  reading transparently), and multi-byte payload decoding.
- **Board** — connection lifecycle (`connect()`/`disconnect()`, serialised by
  a lifecycle lock), a port registry that rejects two drivers sharing one
  socket (`PortInUseError`), and an unlocked-by-design pin-mode cache owned
  per-port by whichever device holds it.
- **Ten device drivers**, each with its own `asyncio.Lock` and cached state:
  `Button`, `Led` (on/off plus PWM `set_brightness`), `Buzzer`
  (cancellation-safe `beep`), `Relay`, `LightSensor`, `SoundSensor`
  (averaging window), `Potentiometer`, `Dht`, `Ultrasonic`, and `RgbLcd`
  (16×2 text plus RGB backlight, on the HAT's I2C port).
- **Testing utilities** — `FakeBridgeFirmware`, a scripted responder that
  emulates the bridge firmware well enough to test any application built on
  groveyard without a Raspberry Pi.
- `examples/` — one small runnable script per module, for confirming the
  library against real hardware, plus a `Makefile` wrapping the development
  gates (`make check`, `make docs`, …).
- Python 3.12–3.14 tested in CI and declared in the package metadata.
- Full typed public API, Google-style docstrings on every public and private
  member, and a 175-test suite covering the happy path, protocol edge cases,
  the concurrency contract, and cancellation safety for every driver.
- Documentation site (this one) covering the architecture, the concurrency
  model, and a guide to writing a new driver.

### Fixed during development (pre-release)

Everything below was found and fixed before this first public release —
several of them by testing against a physical GrovePi+ board, which is also
what this release confirms works end to end (the firmware handshake and the
RGB LCD).

- A DHT reading that failed its sanity check (`NaN` or out-of-range) was
  raised immediately instead of being retried like every other not-ready
  condition; the check now runs inside the protocol layer's retry loop.
- A cancelled `Device.close()` could mark a device closed *before* its
  shutdown actually ran, stranding an energised actuator that every later
  `close()` — including `Board.disconnect()`'s own sweep — would then skip.
- A cancelled `Board.disconnect()` could abandon its shutdown sweep half-way,
  leaving remaining actuators energised and the bus descriptor open; the
  sweep now runs under `asyncio.shield` and always finishes before the
  cancellation is re-raised.
- A second cancellation during `Buzzer.beep()`'s cleanup could abort the
  write that silences the buzzer; that write is now shielded.
- The in-memory fake transport never yielded to the event loop, so several
  concurrency tests (bus-lock non-interleaving, mid-transaction cancellation)
  passed regardless of whether the bus lock actually existed. It now
  suspends on every operation, the way a real transport does inside
  `asyncio.to_thread`.
- `RgbLcd` held the bus lock across the LCD controller's ~50 ms settle
  after every clear or repaint, needlessly stalling every other device on
  the board; the wait now happens with the bus free (`Board.wait()`).
- **Two transports could drive one physical bus with no coordination between
  them.** Every atomicity guarantee in the library is scoped to a single
  `Transport` instance — its bus lock lives on `self`. Nothing stopped a
  caller from building two `SMBusTransport` objects on the same `bus_number`:
  the OS opens `/dev/i2c-<n>` twice quite happily, and the two instances then
  serialised traffic against two locks that knew nothing about each other,
  silently defeating the guarantees documented in the concurrency model.
  `SMBusTransport` now keeps a process-wide registry of open bus numbers,
  guarded by a `threading.Lock` (not `asyncio.Lock` — the whole point is to
  catch a second transport on a second event loop in a second thread, which
  an `asyncio.Lock` cannot serialise against), and rejects the second
  transport with a `TransportError` explaining what to do instead.
- **Every real-hardware read was silently corrupted.** `SMBusSession.read()`
  built the reply with `bytes(bytearray(message))`, where `message` is a
  `smbus2.i2c_msg` — a `ctypes.Structure`. `bytearray()` on a
  `ctypes.Structure` uses the buffer protocol, which returns the
  *structure's own raw memory* (its `addr`/`flags`/`len` fields plus the
  `buf` pointer itself — `ctypes.sizeof(i2c_msg)` bytes, 16 on a 64-bit
  host) instead of the data the pointer refers to, silently bypassing the
  class's own `__iter__`. In practice this meant every single bridged read
  failed with `short read ... expected N, got 16` — none of the 16 bytes
  were ever real device data. Found by testing against a physical board.
  Fixed by using `bytes(message)`, which calls `i2c_msg.__bytes__` and
  correctly dereferences the buffer. Regression-tested with a `ctypes`
  fake shaped exactly like `smbus2.i2c_msg` (a `MagicMock` cannot reproduce
  this class of bug, since it doesn't support the buffer protocol the way a
  real `ctypes.Structure` does). Confirmed fixed against the physical board:
  the firmware-version handshake and the RGB LCD both now complete
  correctly end to end.

See the [architecture documentation](https://quantumwaffy.github.io/groveyard/architecture/)
for the reasoning behind all of the above.

[Unreleased]: https://github.com/quantumwaffy/groveyard/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/quantumwaffy/groveyard/releases/tag/v0.1.2
