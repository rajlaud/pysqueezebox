"""
The following tests check the pysqueezebox.Player module while mocking I/O.
"""
from unittest.mock import AsyncMock, call, patch

import pytest
from pysqueezebox import Player, Server

# pylint: disable=C0103
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_repr():
    """Test the string representation of a Player."""
    test_player = Player(
        "Fake Server", "00:11:22:33:44:55", "Test Player", {"test": "Test"}
    )
    # pylint: disable=eval-used
    test_player2 = eval(repr(test_player))
    assert repr(test_player) == repr(test_player2)


async def test_image_url():
    """Test creating image urls."""
    lms = Server(None, "192.168.1.1", username="test#", password="~/.$password")
    player = Player(lms, "00:11:22:33:44:55", "Test Player")
    assert (
        player.image_url
        == "http://test%23:~%2F.%24password@192.168.1.1:9000/music/unknown/cover.jpg"
    )


async def test_wait():
    """Test player._wait_for_property()."""
    with patch.object(Player, "async_update", AsyncMock()):
        mock_player = Player(None, "00:11:22:33:44:55", "Test Player")
        await mock_player._wait_for_property(None, None, 0)
        mock_player.async_update.assert_not_called()

        assert not await mock_player._wait_for_property(
            "player_id", "55:44:33:22:11:00", 0.1
        )
        mock_player.async_update.assert_called_once()


async def test_verified_pause():
    """Test player._verified_pause_stop."""
    with patch.object(Player, "async_query", AsyncMock(return_val=True)), patch.object(
        Player, "async_update", AsyncMock(return_val=True)
    ), patch.object(Player, "mode", "play"):
        mock_player = Player(None, "11:22:33:44:55", "Test Player")
        assert not await mock_player.async_pause(timeout=0.1)
        pause_args = ["pause", "1"]
        await mock_player.async_query.has_calls([call(pause_args), call(pause_args)])
        mock_player.async_update.assert_called()
