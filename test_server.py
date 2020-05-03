import asyncio

import pytest
from pysqueezebox import Player

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_server_status(lms):
    """Test server.async_status() method."""
    print(await lms.async_status())
    assert lms.uuid is not None  # should be set by async_status()


async def test_get_players(lms):
    """Test server.async_get_players() method."""
    players = await lms.async_get_players()
    for player in players:
        assert isinstance(player, Player)
    await lms.async_status()
    assert len(players) == lms.status["player count"]


async def test_get_player(lms, player):
    """
    Tests server.async_get_player() method.

    Server referenced by 'lms'  must have at least one player active.
    """
    test_player_a = await lms.async_get_player(name=player.name)
    test_player_b = await lms.async_get_player(player_id=player.player_id)
    assert test_player_a.name == test_player_b.name
    assert test_player_a.player_id == test_player_b.player_id

    # test that we properly return None when there is no matching player
    test_player_none = await lms.async_get_player(name="NO SUCH PLAYER")
    assert test_player_none is None
    test_player_none = await lms.async_get_player(player_id="NO SUCH ID")
    assert test_player_none is None

    # check that we handle a name as player_id correctly
    test_player_c = await lms.async_get_player(player.name)
    assert player.player_id == test_player_c.player_id
