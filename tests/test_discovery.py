"""Tests for pysqueezebox.discovery that do not actually require a working server. Does not
attempt to cover code that is covered by the live discovery test in test_integration.py."""

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

import pysqueezebox

# pylint: disable=C0103
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio
pysqueezebox_logger = logging.getLogger("pysqueezebox.discovery")

ADDR = ("192.168.1.1", 9000)
DATA = "bad data"
RESPONSE = {"host": "192.168.1.1", "json": 9000, "name": "test", "uuid": "1234-5678"}


async def test_bad_response():
    """Test handling of a non-LMS discovery response."""
    assert not pysqueezebox.discovery._unpack_discovery_response(DATA, ADDR)

    with patch(
        "pysqueezebox.discovery._unpack_discovery_response", return_value={"addr": ADDR}
    ), patch.object(pysqueezebox_logger, "info") as logger:
        test_protocol = pysqueezebox.discovery.ServerDiscoveryProtocol(None)
        test_protocol.datagram_received(DATA, ADDR)
        logger.assert_called_once()


async def test_callbacks():
    """Test detection and handling of both sync and async callbacks."""
    callback = Mock()
    async_callback = AsyncMock()

    with patch(
        "pysqueezebox.discovery._unpack_discovery_response", return_value=RESPONSE
    ):
        protocol = pysqueezebox.discovery.ServerDiscoveryProtocol(callback)
        async_protocol = pysqueezebox.discovery.ServerDiscoveryProtocol(async_callback)
        protocol.datagram_received(ADDR, DATA)
        async_protocol.datagram_received(ADDR, DATA)

    callback.assert_called_once()
    async_callback.assert_called_once()
