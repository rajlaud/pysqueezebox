"""The pysqueezebox.Server() class."""
import asyncio
import json
import logging
import urllib

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
        self.artists = None
        self.albums = None
        self.titles = None
        self.genres = None

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
                        "Found more than one player matching %s.",
                        name,
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
            async with async_timeout.timeout(TIMEOUT):
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

    async def async_browse(self, category, limit=None, browse_id=None):
        """
        Browse the music library.

        Returns a dictionary with the following keys:
            title: item being browsed, e.g., "Artists", "Jimi Hendrix", "Jazz"
            items: list of dictionaries
              title: title of item
              id: unique identifier for item
              image_url (optional): image url if available. will not be set if unavailable

        Parameters:
            category: playlists, playlist, albums, album, artists, artist, titles, genres, genre
            limit (optional): set maximum number of results
            browse_id (optional): tuple of id type and value
              id type: "album_id", "artist_id", "genre_id", or "track_id"
              value: the id
        """

        browse = {}
        search = f"{browse_id[0]}:{browse_id[1]}" if browse_id else None

        if category in ["playlist", "album", "artist", "genre"]:
            browse["title"] = await self.async_get_category_title(
                category, browse_id[1]
            )
        else:
            browse["title"] = category.title()

        if category in ["playlist", "album"]:
            item_type = "titles"
        elif category in ["genre"]:
            item_type = "artists"
        elif category in ["artist"]:
            item_type = "albums"
        else:
            item_type = category

        items = await self.async_get_category(item_type, limit, search)

        browse["items"] = items
        return browse

    async def async_get_count(self, category):
        """Return number of category in database."""

        result = await self.async_query(category, "0", "1", "count")
        return result["count"]

    async def async_query_category(self, category, limit=None, search=None):
        """Return list of entries in category, optionally filtered by search string."""
        if not limit:
            limit = await self.async_get_count(category)
        if search and "playlist_id" in search:
            # workaround LMS bug - playlist_id doesn't work for "titles" search
            query = ["playlists", "tracks", "0", f"{limit}", search]
            query.append("tags:ju")
            category = "playlisttracks"
        else:
            query = [category, "0", f"{limit}", search]

        if category == "albums":
            query.append("tags:jl")
        elif category == "titles":
            query.append("sort:albumtrack")
            query.append("tags:ju")

        result = await self.async_query(*query)
        if result is None or result.get("count") == 0:
            return None

        try:
            items = result[f"{category}_loop"]
            for item in items:
                if category != "playlisttracks":
                    item["title"] = item.pop(category[:-1])

                if category in ["albums", "titles", "playlisttracks"]:
                    if "artwork_track_id" in item:
                        item["image_url"] = self.generate_image_url_from_track_id(
                            item["artwork_track_id"]
                        )
            return items

        except KeyError:
            _LOGGER.error("Could not find results loop for category %s", category)
            _LOGGER.error("Got result %s", result)

    async def async_get_category(self, category, limit=None, search=None):
        """Update cache of library category if needed and return result."""

        if (
            category not in ["artists", "albums", "titles", "genres"]
            or search is not None
        ):
            return await self.async_query_category(category, limit, search)

        status = await self.async_status()
        if "lastscan" in status and self.__dict__[category] is not None:
            cached_category = self.__dict__[category]
            if status["lastscan"] <= cached_category[0]:
                if limit is None:
                    if cached_category[1] is None:
                        _LOGGER.debug("Using cached category %s", category)
                        return self.__dict__[category][2]
                else:
                    if cached_category[1] is None or limit <= cached_category[1]:
                        _LOGGER.debug(
                            "Using cached category %s with limit %s", category, limit
                        )
                        return self.__dict__[category][2][:limit]

        _LOGGER.debug("Updating cache for category %s", category)
        if self.__dict__[category] is not None:
            _LOGGER.debug(
                "Server lastscan %s different than playlist lastscan %s",
                status.get("lastscan"),
                self.__dict__[category][0],
            )
        else:
            _LOGGER.debug("Category %s not set", category)
        result = await self.async_query_category(category, limit=limit)
        status = await self.async_status()
        self.__dict__[category] = (status.get("lastscan"), limit, result)

        if limit:
            return self.__dict__[category][2][:limit]
        return self.__dict__[category][2]

    async def async_get_category_title(self, category, browse_id):
        """
        Search of the category name corresponding to a title.

        Use the cache because of a bug in how LMS handles this search.
        """
        category_list = await self.async_get_category(f"{category}s")
        result = next(item for item in category_list if item["id"] == int(browse_id))
        if result:
            return result.get("title")

    def generate_image_url_from_track_id(self, track_id):
        """Generate an image url using a track id."""
        return self.generate_image_url(f"/music/{track_id}/cover.jpg")

    def generate_image_url(self, image_url):
        """Add the appropriate base_url to a relative image_url."""

        if self._username:
            base_url = "http://{username}:{password}@{server}:{port}/".format(
                username=self._username,
                password=self._password,
                server=self.host,
                port=self.port,
            )
        else:
            base_url = "http://{server}:{port}/".format(
                server=self.host, port=self.port
            )

        return urllib.parse.urljoin(base_url, image_url)
