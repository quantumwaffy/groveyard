# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) —
while the major version is `0`, a minor bump may still include breaking
changes to the public API.

## [Unreleased]

## [0.1.1] - 2026-08-08

### Fixed

- **Two transports could drive one physical bus with no coordination between
  them.** Every atomicity guarantee in the library is scoped to a single
  `Transport` instance — its bus lock lives on `self`. Nothing stopped a
  caller from building two `SMBusTransport` objects on the same `bus_number`:
  the OS opens `/dev/i2c-<n>` twice quite happily, and the two instances then
  serialised traffic against two locks that knew nothing about each other,
  silently defeating the guarantees documented in the concurrency model.
  `SMBusTransport` now keeps a process-wide registry of open bus numbers and
  rejects the second transport with a `TransportError` explaining what to do
  instead. The reservation is released again if opening fails, is cancelled,
  or if closing the handle raises, so a bus number can never get stuck
  reserved.

  This is a behaviour change for code that was (incorrectly) opening the same
  bus twice: it now fails loudly at `connect()` instead of corrupting traffic
  at random. The guard is per-process; it cannot detect two separate
  *processes* sharing one device node, which would need OS-level file
  locking.

### Added

- Python 3.14 is now tested in CI and declared in the package metadata.
- `examples/` — one small runnable script per module, for confirming the
  library against real hardware, plus a `Makefile` wrapping the development
  gates (`make check`, `make docs`, …).
- A prominent notice in the README that the library has not yet been verified
  on a physical GrovePi+ board, and that feedback from anyone who can test it
  is welcome.

## [0.1.0] - 2026-08-08

Initial release: the full async driver stack for a GrovePi+ starter kit.

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
  (averaging window), `Potentiometer`, `Dht`, `Ultrasonic`, and `RgbLcd` (the
  one native-I2C module, sharing the same bus lock through a different
  address).
- **Testing utilities** — `FakeBridgeFirmware`, a scripted responder that
  emulates the bridge firmware well enough to test any application built on
  groveyard without a Raspberry Pi.
- Full typed public API, Google-style docstrings on every public and private
  member, and a 160+ test suite covering the happy path, protocol edge
  cases, the concurrency contract, and cancellation safety for every driver.
- Documentation site (this one) covering the architecture, the concurrency
  model, and a guide to writing a new driver.

### Fixed during development (pre-release)

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

See the [architecture documentation](https://quantumwaffy.github.io/groveyard/architecture/)
for the reasoning behind all of the above.

[Unreleased]: https://github.com/quantumwaffy/groveyard/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/quantumwaffy/groveyard/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/quantumwaffy/groveyard/releases/tag/v0.1.0
