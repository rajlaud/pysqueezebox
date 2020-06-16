import asyncio
from time import sleep

import pytest
from pysqueezebox import Player

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_remotemeta(player, broken_player):
    """Tests each player property."""
    while True:
        await player.async_update()
        for p in dir(Player):
            prop = getattr(Player, p)
            if isinstance(prop, property):
                print(f"{p}: {prop.fget(player)}")
        print(player._status)
        await asyncio.sleep(5)
