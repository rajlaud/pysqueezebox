"""The pysqueezebox.Server() class."""

import asyncio
import json
import logging
import re
from urllib.parse import quote, unquote, urljoin

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

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        session,
        host,
        port=DEFAULT_PORT,
        username=None,
        password=None,
        uuid=None,
        name=None,
        https=False,
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
        self._prefix = "https" if https else "http"

        self.http_status = None
        self.uuid = uuid
        self.name = name  # often None, can only be found during discovery

        self.status = None
        self._browse_cache = {}  # key: category; value: (lastscan, limit, items)

    def __repr__(self):
        """Return representation of Server object."""
        return (
            f"Server({self.session}, "
            f"{self.host}, "
            f"{self.port}, "
            f"{self._username}, "
            f"{self._password}, "
            f"{self.uuid}, "
            f"{self.name}, "
            f"{self._prefix})"
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
        url = f"{self._prefix}://{self.host}:{self.port}/jsonrpc.js"
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
            category: one of playlists, playlist, albums, album, artists, artist, titles,
              genres, genre, favorites, favorite
            limit (optional): set maximum number of results
            browse_id (optional): tuple of id type and value
              id type: "album_id", "artist_id", "genre_id", or "track_id"
              value: the id
        """
        browse = {}
        search = f"{browse_id[0]}:{browse_id[1]}" if browse_id else None

        if (
            category in ["playlist", "album", "artist", "genre", "favorite"]
            and browse_id
        ):
            browse["title"] = await self.async_get_category_title(category, search)
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
        query = [category]
        if category == "favorites":
            query.append("items")
        query.extend(["0", "1"])
        result = await self.async_query(*query)
        return result["count"]

    async def async_query_category(self, category, limit=None, search=None):
        """Return list of entries in category, optionally filtered by search string."""
        if not limit:
            limit = await self.async_get_count(category)

        if search and "playlist_id" in search:
            # workaround LMS bug - playlist_id doesn't work for "titles" search
            query = ["playlists", "tracks", "0", f"{limit}", search]
            query.append("tags:ju")
        elif search and "item_id" in search:
            # we have to look up favorites separately
            query = ["favorites", "items", "0", f"{limit}", search]
        else:
            if category in ["favorite", "favorites"]:
                query = ["favorites", "items"]
            else:
                query = [category]
            query.extend(["0", f"{limit}", search])

        # add command-specific suffixes
        if query[0] == "albums":
            query.append("tags:jla")
        elif query[0] == "titles":
            query.append("sort:albumtrack")
            query.append("tags:ju")
        elif query[0] == "favorites":
            query.append("want_url:1")

        result = await self.async_query(*query)
        if not result or result.get("count") == 0:
            return None

        items = None
        try:
            if query[0] == "favorites":
                items = result["loop_loop"]  # strange, but what LMS returns
            else:
                items = result[f"{category}_loop"]
            for item in items:
                if query[0] == "favorites":
                    if item["isaudio"] != 1 and item["hasitems"] != 1:
                        continue
                    item["title"] = item.pop("name")
                    if item.get("url", "").startswith("db:album.title"):
                        item["album_id"] = await self.async_get_album_id_from_url(
                            item["url"]
                        )
                    if "image" in item:
                        item["image_url"] = self.generate_image_url(item.pop("image"))
                        if track_id := self.get_track_id_from_image_url(
                            item["image_url"]
                        ):
                            item["artwork_track_id"] = track_id
                elif query[0] not in ["playlists", "favorites"]:
                    item["title"] = item.pop(category[:-1])

                if "artwork_track_id" in item:
                    item["image_url"] = self.generate_image_url_from_track_id(
                        item["artwork_track_id"]
                    )
            return items

        except KeyError:
            if not items:
                _LOGGER.error("Could not find results loop for category %s", category)
                _LOGGER.error("Got result %s", result)
            else:
                raise

    async def async_get_category(self, category, limit=None, search=None):
        """Update cache of library category if needed and return result."""
        if (
            category not in ["artists", "albums", "titles", "genres"]
            or search is not None
        ):
            return await self.async_query_category(category, limit, search)

        status = await self.async_status()
        cached_category = self._browse_cache.get(category)
        if "lastscan" in status and cached_category is not None:
            if status["lastscan"] <= cached_category[0]:
                if cached_category[2] is None:
                    return None
                if limit is None:
                    if cached_category[1] is None:
                        _LOGGER.debug("Using cached category %s", category)
                        return cached_category[2]
                else:
                    if cached_category[1] is None or limit <= cached_category[1]:
                        _LOGGER.debug(
                            "Using cached category %s with limit %s", category, limit
                        )
                        return cached_category[2][:limit]

        _LOGGER.debug("Updating cache for category %s", category)
        if cached_category is not None:
            _LOGGER.debug(
                "Server lastscan %s different than playlist lastscan %s",
                status.get("lastscan"),
                cached_category[0],
            )
        else:
            _LOGGER.debug("Category %s not set", category)
        result = await self.async_query_category(category, limit=limit)
        status = await self.async_status()

        # only save useful results where library has lastscan value
        if status["lastscan"] is not None:
            self._browse_cache[category] = (status.get("lastscan"), limit, result)
        else:
            self._browse_cache[category] = None

        if limit and result:
            return result[:limit]
        return result

    async def async_get_category_title(self, category, search):
        """
        Search of the category name corresponding to a title.
        """
        result = await self.async_get_category(f"{category}s", 50, search)
        if result and len(result) > 0:
            return result[0].get("title")

    async def async_get_album_id_from_url(self, url):
        """Find the album_id from a favorites url."""
        album_seach_string = unquote(url)[15:].split("&contributor.name=")
        album_title = album_seach_string[0]
        album_contributor = (
            album_seach_string[1] if len(album_seach_string) > 1 else None
        )

        albums = await self.async_get_category("albums")
        for album in albums:
            if album["title"] == album_title:
                if album_contributor:
                    if album["artist"] == album_contributor:
                        return album["id"]
                else:
                    return album["id"]
            else:
                continue

    def generate_image_url_from_track_id(self, track_id):
        """Generate an image url using a track id."""
        return self.generate_image_url(f"/music/{track_id}/cover.jpg")

    def get_track_id_from_image_url(self, image_url):
        """Get a track id from an image url."""

        match = re.search(r"^(?:/?)music/([^/]+)/cover.*", image_url)
        if match:
            return match.group(1)
        return None

    def generate_image_url(self, image_url):
        """Add the appropriate base_url to a relative image_url."""
        base_url = f"{self._prefix}://"
        if self._username:
            base_url += quote(self._username, safe="")
            base_url += ":"
            base_url += quote(self._password, safe="")
            base_url += "@"

        base_url += f"{self.host}:{self.port}/"

        return urljoin(base_url, image_url)
