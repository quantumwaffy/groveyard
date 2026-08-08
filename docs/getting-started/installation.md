# Installation

groveyard targets **Python 3.12+** and is split into a pure-Python core plus
an optional hardware extra, so installing it never requires a Raspberry Pi.

=== "On a Raspberry Pi"

    ```bash
    pip install "groveyard[hardware]"
    ```

    The `hardware` extra pulls in [`smbus2`][smbus2], the only runtime
    dependency, which talks to `/dev/i2c-1`. It is optional because nothing
    else in the library imports it — see
    [why `smbus2` is optional](../architecture/index.md#the-transport-layer).

=== "Anywhere else (develop, test, CI)"

    ```bash
    pip install groveyard
    ```

    Without the extra you get the full public API plus
    [`FakeTransport`][groveyard.FakeTransport] and
    [`FakeBridgeFirmware`][groveyard.testing.FakeBridgeFirmware] — enough to
    write and run an entire application's test suite. See
    [Testing without hardware](../guides/testing.md).

=== "With uv"

    ```bash
    uv add "groveyard[hardware]"   # on the Pi
    uv add groveyard               # anywhere else
    ```

!!! tip "Enabling I2C on the Pi"
    If this is a fresh Raspberry Pi OS install, enable the I2C interface first
    with `sudo raspi-config` → *Interface Options* → *I2C*, and add your user
    to the `i2c` group (`sudo usermod -aG i2c $USER`, then log out and back
    in). [`SMBusTransport`][groveyard.SMBusTransport] raises a clear
    [`TransportError`][groveyard.TransportError] if the bus cannot be opened.

## Contributing to groveyard itself

Cloning the repository to work on the library uses [uv](https://docs.astral.sh/uv/)
for environment and dependency management:

```bash
git clone https://github.com/quantumwaffy/groveyard.git
cd groveyard
uv sync --all-groups
```

See [Contributing](../contributing.md) for the full development workflow.

[smbus2]: https://pypi.org/project/smbus2/
