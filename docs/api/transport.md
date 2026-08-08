# Transport

The transport layer owns the bus handle and the single bus-wide lock. See
[Concurrency model](../architecture/concurrency.md) for how it is used.

## Abstractions

::: groveyard.transport.base
    options:
      show_root_heading: false
      members: false

::: groveyard.Transport

::: groveyard.transport.base.BusSession
    options:
      show_root_heading: true

::: groveyard.RetryPolicy

## Real hardware: `smbus2`

::: groveyard.transport.i2c
    options:
      show_root_heading: false
      members: false

::: groveyard.SMBusTransport

## In-memory fake

Used throughout this library's own test suite, and shipped for use in yours
— see [Testing without hardware](../guides/testing.md).

::: groveyard.transport.fake
    options:
      show_root_heading: false
      members: false

::: groveyard.FakeTransport

::: groveyard.transport.fake.FakeSession
    options:
      show_root_heading: true

::: groveyard.transport.fake.BusResponder
    options:
      show_root_heading: true

### Recorded events

::: groveyard.transport.fake.BusWrite
    options:
      show_root_heading: true

::: groveyard.transport.fake.BusRead
    options:
      show_root_heading: true

::: groveyard.transport.fake.BusRegisterWrite
    options:
      show_root_heading: true

::: groveyard.transport.fake.BusSettle
    options:
      show_root_heading: true
