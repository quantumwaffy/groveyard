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

## Enabling I2C on the Pi

On a fresh install the I2C interface is off by default. How you turn it on
depends on the OS image.

=== "Raspberry Pi OS"

    `raspi-config` ships preinstalled:

    ```bash
    sudo raspi-config   # Interface Options -> I2C -> yes
    ```

=== "Ubuntu Server (24.04 LTS)"

    `raspi-config` is **not** preinstalled, but it does not need a third-party
    repository either — Ubuntu already carries it in its own `universe`
    component:

    ```bash
    sudo apt update
    sudo apt install raspi-config
    sudo raspi-config   # Interface Options -> I2C -> yes
    ```

    Confirmed against a real Raspberry Pi running Ubuntu 24.04 LTS
    (`6.8.0-raspi`, aarch64): this correctly enables `dtparam=i2c_arm=on` in
    `/boot/firmware/config.txt` and loads the `i2c-dev` kernel module at boot,
    even though `raspi-config` itself targets Raspberry Pi OS.

    Prefer not to install a Raspberry Pi OS tool on Ubuntu at all? The two
    steps above are just file edits — do them directly instead:

    ```bash
    # 1. Enable the interface in the boot firmware config
    sudo sed -i 's/^#\(dtparam=i2c_arm=on\)/\1/' /boot/firmware/config.txt
    grep -qx 'dtparam=i2c_arm=on' /boot/firmware/config.txt || \
      echo 'dtparam=i2c_arm=on' | sudo tee -a /boot/firmware/config.txt

    # 2. Load the i2c-dev module at every boot
    echo 'i2c-dev' | sudo tee /etc/modules-load.d/i2c.conf
    ```

Either way, finish with:

```bash
sudo apt install i2c-tools       # optional: i2cdetect/i2cget/i2cset for manual
                                  # diagnostics — groveyard itself never needs it
sudo usermod -aG i2c $USER       # let your user open /dev/i2c-1 without sudo
sudo reboot                      # dtparam changes and the new group both need one
```

### Verifying it worked

```bash
ls -l /dev/i2c-1   # should exist, group "i2c"
groups              # should list "i2c" for your user
i2cdetect -y 1       # should print a 16x16 grid, no errors opening the bus
```

!!! warning "`i2cdetect` will not show `0x04`, even when everything works"
    The GrovePi+ bridge firmware only answers a real 4-byte command
    (`docs/protocol.md` §2) — `i2cdetect`'s address-probe is a 0-byte
    transaction the firmware silently ignores. Seeing an empty row at `0x04`
    is expected, not a sign the HAT is dead; [`Board.on_i2c()`][groveyard.Board.on_i2c]
    talks to it with real commands and that is the check that matters.
    Native-I2C devices such as the RGB LCD (`0x3e`, `0x62`) *do* show up here
    if plugged in.

[`SMBusTransport`][groveyard.SMBusTransport] raises a clear
[`TransportError`][groveyard.TransportError] if the bus still cannot be
opened after all of the above.

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
