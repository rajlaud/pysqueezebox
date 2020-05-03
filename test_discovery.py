import asyncio
from time import sleep

import aiohttp
import pytest
from pysqueezebox import Player, Server, async_discover

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def session(event_loop):
    print("Created LMS session")
    async with aiohttp.ClientSession() as session:
        yield session


async def test_discovery(event_loop):
    task = asyncio.create_task(async_discover(_discovery_callback))
    await asyncio.sleep(10)
    print("Cancelling task")
    task.cancel()
    await task
    task = asyncio.create_task(async_discover(_async_discovery_callback))
    await asyncio.sleep(10)
    task.cancel()
    await task


def _discovery_callback(server):
    print(server)


async def _async_discovery_callback(server):
    print(server)
    try:
        await server.async_status()
    except ValueError as exc:
        print(exc)
        pass
