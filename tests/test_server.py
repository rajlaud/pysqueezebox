"""
The following tests check the pysqueezebox.Server module while mocking I/O.
"""
import asyncio
from unittest.mock import Mock, patch

import pytest
from aiohttp import ClientSession
from asynctest import CoroutineMock
from pysqueezebox import Server

# pylint: disable=C0103
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_get_players():
    """Test async_get_players() method."""
    with patch.object(Server, "async_query", CoroutineMock(return_value=False)):
        mock_lms = Server(None, None)
        await mock_lms.async_get_players()
        assert await mock_lms.async_get_player() is None


async def test_async_query():
    """Test async_query failure modes (successful queries tested by test_integration.py)."""
    lms = Server(None, None)
    with pytest.raises(ValueError):
        assert await lms.async_query("serverstatus")

    response = Mock(status="404", text="could not find page")
    with patch.object(ClientSession, "post", CoroutineMock(return_value=response)):
        mock_lms = Server(ClientSession(), None)
        assert not await mock_lms.async_query("serverstatus")

    with patch.object(
        ClientSession, "post", CoroutineMock(side_effect=asyncio.TimeoutError)
    ):
        mock_lms = Server(ClientSession(), None)
        assert not await mock_lms.async_query("serverstatus")

    data = {"bogus_key": "bogus_value"}
    response = Mock(status=200, json=CoroutineMock(return_value=data))
    with patch.object(ClientSession, "post", CoroutineMock(return_value=response)):
        mock_lms = Server(ClientSession(), None)
        assert not await mock_lms.async_query("serverstatus")
