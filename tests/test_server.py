"""
The following tests check the pysqueezebox.Server module while mocking I/O.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import ClientSession
from pysqueezebox import Server

# pylint: disable=C0103
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_get_players() -> None:
    """Test async_get_players() method."""
    with patch.object(Server, "async_query", AsyncMock(return_value=None)):
        mock_lms = Server(ClientSession(), "fake-server.internal")
        await mock_lms.async_get_players()
        assert await mock_lms.async_get_player() is None


async def test_async_query() -> None:
    """Test async_query failure modes (successful queries tested by test_integration.py)."""
    lms = Server(None, "fake-server.internal")
    with pytest.raises(ValueError):
        assert await lms.async_query("serverstatus") is None

    response = Mock(status="404", text="could not find page")
    with patch.object(ClientSession, "post", AsyncMock(return_value=response)):
        mock_lms = Server(ClientSession(), "fake-server.internal")
        assert not await mock_lms.async_query("serverstatus")

    with patch.object(
        ClientSession, "post", AsyncMock(side_effect=asyncio.TimeoutError)
    ):
        mock_lms = Server(ClientSession(), "fake-server.internal")
        assert not await mock_lms.async_query("serverstatus")

    data = {"bogus_key": "bogus_value"}
    response = Mock(status=200, json=AsyncMock(return_value=data))
    with patch.object(ClientSession, "post", AsyncMock(return_value=response)):
        mock_lms = Server(ClientSession(), "fake-server.internal")
        assert not await mock_lms.async_query("serverstatus")
