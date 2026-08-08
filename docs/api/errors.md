# Errors

Every exception the library raises derives from [`GroveyardError`][groveyard.GroveyardError].
Out-of-range arguments and other caller mistakes intentionally raise the
built-in `ValueError` / `TypeError` instead — see the module docstring below
for the reasoning.

::: groveyard.errors
    options:
      show_root_heading: false
      members: false

::: groveyard.GroveyardError

::: groveyard.TransportError

::: groveyard.ProtocolError

::: groveyard.DeviceNotReadyError

::: groveyard.DeviceError

::: groveyard.DeviceClosedError

::: groveyard.BoardError

::: groveyard.NotConnectedError

::: groveyard.PortInUseError
