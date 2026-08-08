"""Typed exception hierarchy for the whole library.

Every failure raised by groveyard derives from :class:`GroveyardError`, so callers
can catch the whole library with one ``except`` clause and still discriminate
between a bus fault, a malformed reply and a device that is not ready yet.

Programming errors (an out-of-range argument, a wrong port kind) intentionally
raise the built-in :class:`ValueError` / :class:`TypeError` instead: they are bugs
in the caller, not runtime conditions to be handled.
"""


class GroveyardError(Exception):
    """Base class for every error raised by groveyard."""


class TransportError(GroveyardError):
    """The I2C bus itself failed.

    Raised when the underlying bus handle reports an OS-level error (the board is
    unplugged, the bus is not enabled, the address does not acknowledge) and the
    transport's bounded retries have been exhausted.
    """


class ProtocolError(GroveyardError):
    """The board answered, but the reply does not match the wire protocol.

    Typical causes are a truncated reply or an echo byte that does not match the
    command that was sent, which means the bus transaction was torn or the board
    is running incompatible firmware. See ``docs/protocol.md`` section 2.
    """


class DeviceNotReadyError(GroveyardError):
    """The board answered with a "not ready yet" sentinel.

    The bridge firmware replies with ``23`` (``data_not_available``) or ``255``
    when the requested measurement has not been serviced yet. The protocol layer
    retries such replies a bounded number of times; this error surfaces only when
    the board is still not ready after the last attempt.
    """


class DeviceError(GroveyardError):
    """Base class for errors about a single device's lifecycle."""


class DeviceClosedError(DeviceError):
    """A device was used after it had been closed.

    Closing a driver releases its port and drives actuators back to *off*, so the
    instance is deliberately not reusable: build a new one.
    """


class BoardError(GroveyardError):
    """Base class for errors about board lifecycle and port allocation."""


class NotConnectedError(BoardError):
    """An operation needed an open connection that the board does not have.

    Raised when a device is used before :meth:`groveyard.board.Board.connect` or
    after :meth:`groveyard.board.Board.disconnect`.
    """


class PortInUseError(BoardError):
    """Two devices tried to claim the same physical port.

    Each port carries exactly one module, and each device caches the pin mode of
    its own port. Allowing two drivers on one port would let them fight over that
    cached state, so the second driver is rejected at construction time.
    """
