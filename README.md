# pysqueezebox - Asynchronous control of squeezeboxes
This a library to control a Logitech Media Server asynchronously, intended for
integration with Home Assistant.

Much of the code was adapted from the Home Assistant squeezebox integration.
The current convention is for all API-specific code to be part of a third
party library hosted on PyPi, so I created a separate library.

The function names track the terms used by the LMS API, so they do not all
match the old Home Assistant squeezebox integration.

Thank you to the original author of the squeezebox integration. If it is you,
please let me know so I can credit you here.

# Usage
Install pysqueezebox from github, or using PyPi via pip.
```sh
$ pip3 install pysqueezebox
```

## Imports
Import the Server() and Player() classes from this module. You will also need
to create an aiohttp.ClientSession() that the module will use to communicate
with the Logitech Media Server.

You can use Server.async_get_players() to retrieve a list of connected players,
or get a specific player using Server.async_get_player(name="PlayerName").
Remember that any method starting with "async_" is a coroutine that must be
preceded by an await to run.

For more information on using aiohttp.ClientSession(), see
https://aiohttp.readthedocs.io/en/stable/client_reference.html.
```Python
from pysqueezebox import Server, Player
import aiohttp
import asyncio
SERVER = '192.168.1.2' # ip address of Logitech Media Server

async def main():
    async with aiohttp.ClientSession() as session:
        lms = Server(session, SERVER)
        player = await lms.async_get_player(name="Bedroom")
	await player.async_update()
	print(player.album)
	await player.async_play()

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
```

## Player.async_update()
The Player object stores information about the current status of the player.
This allows you to retrieve the player's properties without any I/O. Remember
to call Player.async_update() prior to retrieving properties if you want the
most up-to-date information.

## Player() class
Most of the useful functions are in the Player class. More documentation to
follow, but in the meantime, the docstrings should be instructive.
