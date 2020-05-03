"""Shared fixtures for testing pysqueezebox."""
import asyncio

import aiohttp
import pytest
from pysqueezebox import Player, Server

SERVER = "192.168.2.2"
PLAYER = "Tape"


@pytest.fixture(scope="module")
def event_loop():
    """Return an event loop for testing async functions."""
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def lms(event_loop):
    """Return a working Server object."""
    print("Created LMS session")
    async with aiohttp.ClientSession() as session:
        lms = Server(session, SERVER)
        # confirm server is working
        assert await lms.async_status()
        yield lms


@pytest.fixture(scope="module")
async def player(lms):
    """Return a working Player object."""
    if PLAYER:
        player = await lms.async_get_player(name=PLAYER)
    else:
        players = await lms.async_get_players()
        player = players[0]
    assert isinstance(player, Player)
    assert await player.async_update()
    yield player


@pytest.fixture(scope="module")
async def broken_player(lms):
    """Return a Player that does not work."""
    broken_player = Player(lms, "NOT A PLAYER ID", "Bogus player")
    assert not await broken_player.async_update()
    yield broken_player
