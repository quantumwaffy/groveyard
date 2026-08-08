"""Shared fixtures: every test runs against the in-memory fake, never hardware."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from groveyard.board import Board
from groveyard.testing.firmware import FakeBridgeFirmware
from groveyard.transport.fake import FakeTransport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
def firmware() -> FakeBridgeFirmware:
    """A board whose pins a test can configure before acting."""
    return FakeBridgeFirmware()


@pytest.fixture
def transport(firmware: FakeBridgeFirmware) -> FakeTransport:
    """A recording transport wired to the fake firmware."""
    return FakeTransport(responder=firmware)


@pytest.fixture
async def board(transport: FakeTransport) -> AsyncIterator[Board]:
    """A connected board, disconnected again when the test ends."""
    async with Board(transport) as connected:
        yield connected
