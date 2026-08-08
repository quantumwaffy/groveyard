# Device base classes

Every driver builds on one of these. See
[Writing a new driver](../../guides/new-driver.md) for a worked example, and
the *Locking discipline* section below for the `*_locked` convention every
driver follows.

::: groveyard.devices.base
    options:
      show_root_heading: false
      members: false

::: groveyard.Device

::: groveyard.PortDevice

::: groveyard.BridgedDevice

::: groveyard.I2CDevice

::: groveyard.DigitalInputDevice

::: groveyard.DigitalOutputDevice

::: groveyard.AnalogInputDevice
