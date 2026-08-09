"""Regression test for a ctypes buffer-protocol pitfall in SMBusSession.read().

``smbus2.i2c_msg`` is a ``ctypes.Structure``. ``bytearray()`` on a
``ctypes.Structure`` uses the buffer protocol and returns the structure's own
raw memory — its declared fields (``addr``, ``flags``, ``len``) plus the
``buf`` pointer *itself*, ``ctypes.sizeof(i2c_msg)`` bytes (16 on a 64-bit
host) — completely bypassing the class's own ``__iter__``. ``bytes()``, in
contrast, calls ``__bytes__`` if the class defines one, which is what
correctly dereferences the pointer and returns the real reply.

``unittest.mock.MagicMock``, used everywhere else in this test suite to fake
``smbus2``, cannot catch this: the bug only exists because the real class is a
``ctypes.Structure``, and a mock is not one. This is what a GrovePi+ on real
hardware hit on the very first read: every reply came back as "short read ...
expected 4, got 16", where 16 was never data from the device at all — it was
the message object's own memory layout, misread as a reply.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, c_char, c_uint16, create_string_buffer, string_at
from typing import ClassVar

from groveyard.transport.base import RetryPolicy
from groveyard.transport.i2c import SMBusSession


class FakeI2cMsg(Structure):
    """A ``ctypes.Structure`` shaped exactly like ``smbus2.i2c_msg``.

    The *shape* is what matters here, not just the interface: a plain Python
    object with matching ``__iter__``/``__bytes__`` methods would not
    reproduce the bug, because it would not support the buffer protocol the
    way a real ``ctypes.Structure`` does.
    """

    _fields_: ClassVar = [
        ("addr", c_uint16),
        ("flags", c_uint16),
        ("len", c_uint16),
        ("buf", POINTER(c_char)),
    ]

    def __iter__(self):  # noqa: ANN204 - mirrors smbus2.i2c_msg exactly, including its untyped __iter__
        """Iterate over the received bytes, the way ``smbus2.i2c_msg`` does."""
        idx = 0
        while idx < self.len:
            yield ord(self.buf[idx])
            idx += 1

    def __bytes__(self) -> bytes:
        """Return the received bytes by dereferencing ``buf``, exactly ``len`` of them."""
        return string_at(self.buf, self.len)


class FakeI2cMsgFactory:
    """Mimics ``smbus2.i2c_msg``'s two static builder methods."""

    @staticmethod
    def read(address: int, length: int) -> FakeI2cMsg:
        """Build a read message with an empty, correctly sized buffer."""
        buf = create_string_buffer(length)
        return FakeI2cMsg(addr=address, flags=1, len=length, buf=buf)

    @staticmethod
    def write(address: int, data: bytes) -> FakeI2cMsg:
        """Build a write message carrying ``data``."""
        buf = create_string_buffer(bytes(data), len(data))
        return FakeI2cMsg(addr=address, flags=0, len=len(data), buf=buf)


class FakeBusHandle:
    """Simulates the kernel filling a read message's buffer during ``i2c_rdwr``.

    A real ``smbus2.SMBus`` fills the buffer via the ``I2C_RDWR`` ioctl; from
    Python's side the observable effect is identical either way: after the
    call, ``message.buf`` points at the reply bytes.
    """

    def __init__(self) -> None:
        self._replies: list[bytes] = []

    def queue_reply(self, reply: bytes) -> None:
        """Script the bytes the next read message will be filled with."""
        self._replies.append(reply)

    def i2c_rdwr(self, *messages: object) -> None:
        """Fill each read message's buffer from the queue; ignore write messages."""
        for message in messages:
            assert isinstance(message, FakeI2cMsg)
            is_read = bool(message.flags & 1)
            if is_read:
                reply = self._replies.pop(0)
                assert len(reply) == message.len
                ctypes.memmove(message.buf, reply, len(reply))

    def write_byte_data(self, address: int, register: int, value: int) -> None:
        """Unused by this test; present only to satisfy the structural type."""
        raise NotImplementedError

    def close(self) -> None:
        """Unused by this test; present only to satisfy the structural type."""


async def test_read_returns_the_reply_bytes_not_the_ctypes_struct_layout() -> None:
    """``read()`` must use ``bytes(message)``, never ``bytes(bytearray(message))``."""
    bus = FakeBusHandle()
    bus.queue_reply(bytes([8, 1, 4, 0]))  # a plausible firmware-version reply
    session = SMBusSession(bus, FakeI2cMsgFactory(), RetryPolicy())

    data = await session.read(0x04, 4)

    assert data == bytes([8, 1, 4, 0])


async def test_read_of_exactly_sizeof_i2c_msg_bytes_still_returns_the_real_reply() -> None:
    """The sharpest possible case: a real command that needs exactly 16 bytes.

    On a 64-bit host ``ctypes.sizeof(i2c_msg)`` is 16, which is also what the
    buggy code always produced regardless of what was requested. A 16-byte
    read is the one size for which the old, broken length check could not
    catch the bug by accident — so this asserts on *content*, not just length.
    """
    bus = FakeBusHandle()
    reply = bytes(range(16))
    bus.queue_reply(reply)
    session = SMBusSession(bus, FakeI2cMsgFactory(), RetryPolicy())

    data = await session.read(0x62, 16)

    assert data == reply
