"""The pysqueezebox.Server() class."""
import asyncio
import json
import logging

import aiohttp
import async_timeout

from .const import DEFAULT_PORT, TIMEOUT
from .player import Player

_LOGGER = logging.getLogger(__name__)


# pylint: disable=too-many-instance-attributes
class Server:
    """
    Represents a Logitech media server.

    Right now, only those features used by the pre-existing Home Assistant
    squeezebox integration are implemented.
    """

    # pylint: disable=too-many-arguments, bad-continuation
    def __init__(
        self,
        session,
        host,
        port=DEFAULT_PORT,
        username=None,
        password=None,
        uuid=None,
        name=None,
    ):
        """
        Initialize the Logitech device.

        Parameters:
            session: aiohttp.ClientSession for connecting to server (required)
            host: LMS server to connect with (required)
            port: LMS server port (optional, default 9000)
            username: LMS username (optional)
            password: LMS password (optional)
            uuid: LMS uuid (optional, will be updated on first async_status() call)
            name: LMS server name (optional, only available through discovery)
        """
        self.host = host
        self.port = port
        self.session = session
        self._username = username
        self._password = password

        self.http_status = None
        self.uuid = uuid
        self.name = name  # often None, can only be found during discovery

        self.status = None

    def __repr__(self):
        """Return representation of Server object."""
        return (
            f"Server({self.session}, "
            f"{self.host}, "
            f"{self.port}, "
            f"{self._username}, "
            f"{self._password}, "
            f"{self.uuid}, "
            f"{self.name})"
        )

    async def async_get_players(self, search=None):
        """
        Return Player for each device connected to LMS.

        Parameters:
            search: filter the result by case-insensitive substring (optional)
        """
        players = []
        data = await self.async_query("players", "status")
        if data is False:
            return None
        for player in data.get("players_loop", []):
            if search:
                if search.lower() in player["name"].lower():
                    players.append(Player(self, player["playerid"], player["name"]))
            else:
                players.append(Player(self, player["playerid"], player["name"]))
        _LOGGER.debug("get_players(%s) returning players: %s", search, players)
        return players

    async def async_get_player(self, player_id=None, name=None):
        """
        Return Player for a device connected to server.

        Parameters (one required):
            player_id: The unique player_id reported by the server.
            name: A substring for a case-insensitive match. Will return first of
                  multiple matching results.
        """
        if player_id:
            data = await self.async_query("status", player=player_id)
            if data:
                # an exact, case sensitive string match on the player name will
                # also return a result. if that happened, search on name instead
                # to retrieve accurate player_id
                if player_id == data.get("player_name"):
                    _LOGGER.info(
                        "get_player(player_id=%s) called with player name.", player_id
                    )
                    return await self.async_get_player(name=player_id)
                if "player_name" in data:
                    return Player(self, player_id, data["player_name"])
            _LOGGER.debug("Unable to find player with player_id: %s", player_id)
            return None
        if name:
            players = await self.async_get_players(name)
            if len(players) >= 1:
                if len(players) > 1:
                    _LOGGER.warning(
                        "Found more than one player matching %s.", name,
                    )
                _LOGGER.debug("get_player(name=%s) return player %s.", name, players[0])
                return players[0]
            _LOGGER.debug("Unable to find player with name: %s.", name)
            return None
        _LOGGER.error("get_player() called without name or player_id.")
        return None

    async def async_status(self):
        """Return status of current server."""
        self.status = await self.async_query("serverstatus")
        if self.status:
            if self.uuid is None and "uuid" in self.status:
                self.uuid = self.status["uuid"]
        return self.status

    async def async_query(self, *command, player=""):
        """Return result of query on the JSON-RPC connection."""
        auth = (
            None
            if self._username is None
            else aiohttp.BasicAuth(self._username, self._password)
        )
        url = f"http://{self.host}:{self.port}/jsonrpc.js"
        data = json.dumps(
            {"id": "1", "method": "slim.request", "params": [player, command]}
        )

        _LOGGER.debug("URL: %s Data: %s", url, data)

        if self.session is None:
            raise ValueError("async_query() called with Server.session unset")

        try:
            with async_timeout.timeout(TIMEOUT):
                response = await self.session.post(url, data=data, auth=auth)
                self.http_status = response.status

                if response.status != 200:
                    _LOGGER.info(
                        "Query failed, response code: %s Full message: %s",
                        response.status,
                        response,
                    )
                    return False

                data = await response.json()

        except aiohttp.ServerDisconnectedError as error:
            # LMS handles an unknown player by abruptly disconnecting
            if player:
                _LOGGER.info("Query run on unknown player %s", player)
            else:
                _LOGGER.error("Failed communicating with LMS: %s", type(error))
            return False

        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            _LOGGER.error("Failed communicating with LMS: %s", type(error))
            return False

        try:
            result = data["result"]
            if not result:
                # a successful command will return an empty result
                return True
            return result
        except KeyError:
            _LOGGER.error("Received invalid response: %s", data)
