"""
The following tests check the pysqueezebox.Player module while mocking I/O.
"""

from unittest.mock import AsyncMock, call, patch

import pytest
from pysqueezebox import Player, Server

# pylint: disable=C0103
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_repr() -> None:
    """Test the string representation of a Player."""
    mock_server = Server(None, "test")
    test_player = Player(mock_server, "00:11:22:33:44:55", "Test Player")
    # pylint: disable=eval-used
    test_player2 = eval(repr(test_player))
    assert repr(test_player) == repr(test_player2)


async def test_image_url() -> None:
    """Test creating image urls."""
    mock_server = Server(None, "192.168.1.1", username="test#", password="~/.$password")
    player = Player(mock_server, "00:11:22:33:44:55", "Test Player")
    assert (
        player.image_url
        == "http://test%23:~%2F.%24password@192.168.1.1:9000/music/unknown/cover.jpg"
    )


async def test_wait() -> None:
    """Test player._wait_for_property()."""
    with patch.object(Player, "async_update", AsyncMock()) as mock_update:
        mock_server = AsyncMock(autospec=Server)
        mock_player = Player(mock_server, "00:11:22:33:44:55", "Test Player")
        await mock_player._wait_for_property("player_id", "wrong one", 0)
        mock_update.assert_not_called()

        assert not await mock_player._wait_for_property(
            "player_id", "55:44:33:22:11:00", 0.1
        )
        mock_update.assert_called_once()


async def test_verified_pause() -> None:
    """Test player._verified_pause_stop."""
    with patch.object(
        Player, "async_command", AsyncMock(return_val=True)
    ) as mock_command, patch.object(
        Player, "async_update", AsyncMock(return_val=True)
    ) as mock_update, patch.object(
        Player, "mode", "play"
    ):
        mock_server = AsyncMock(autospec=Server)
        mock_player = Player(mock_server, "11:22:33:44:55", "Test Player")
        assert not await mock_player.async_pause(timeout=0.1)
        pause_args = ["pause", "1"]
        mock_command.has_calls([call(pause_args), call(pause_args)])
        mock_update.assert_called()
