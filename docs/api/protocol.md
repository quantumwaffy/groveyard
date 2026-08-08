# Protocol

Encoding and decoding of the `0x04` bridge firmware command set. See
[Wire protocol](../protocol.md) for the hardware-facing specification this
module implements. `BridgeProtocol` itself is an implementation detail
[`Board`][groveyard.Board] wraps — most applications never construct it
directly, which is why it is documented here by its full path rather than a
top-level alias.

::: groveyard.protocol.commands
    options:
      show_root_heading: false

::: groveyard.protocol.bridge
    options:
      show_root_heading: false
      members: false

::: groveyard.protocol.bridge.BridgeProtocol
    options:
      show_root_heading: true

::: groveyard.FirmwareVersion
