"""The pysqueezebox.Server() class."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib

from typing import Any, TypedDict

import aiohttp
import async_timeout

from .const import DEFAULT_PORT, TIMEOUT, QueryResult
from .player import Player, PlayerStatus

_LOGGER = logging.getLogger(__name__)

# type hints

ServerStatus = TypedDict(
    "ServerStatus",
    {
        "rescan": str,
        "lastscan": str,
        "progressname": str,
        "progressdone": str,
        "progresstotal": str,
        "lastscanfailed": str,
        "version": str,
        "mac": str,
        "ip": str,
        "httpport": str,
        "uuid": str,
        "info total albums": str,
        "info total artists": str,
        "info total songs": str,
        "info total genres": str,
        "player count": str,
        "players_loop": list[PlayerStatus],
    },
    total=False,
)


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
        session: aiohttp.ClientSession | None,
        host: str,
        port: int = DEFAULT_PORT,
        username: str | None = None,
        password: str | None = None,
        uuid: str | None = None,
        name: str | None = None,
        https: bool = False,
    ) -> None:
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

        self.http_status: int | None = None
        self.uuid = uuid
        self.name = name  # often None, can only be found during discovery

        self.status: dict[str, Any] | None = None
        self._browse_cache: dict[
            str, tuple[int, int | None, list[QueryResult] | None] | None
        ] = {}  # key: category; value: (lastscan, limit, items)

    def __repr__(self) -> str:
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

    async def async_get_players(self, search: str | None = None) -> list[Player] | None:
        """
        Return Player for each device connected to LMS.

        Parameters:
            search: filter the result by case-insensitive substring (optional)
        """
        players: list[Player] = []
        data = await self.async_query("players", "status")
        if (
            data is None
            or "players_loop" not in data
            or not isinstance(data["players_loop"], list)
        ):
            return None
        for player in data["players_loop"]:
            if (
                not isinstance(player, dict)
                or "playerid" not in player
                or "name" not in player
            ):
                _LOGGER.error(
                    "Received invalid response from LMS for player: %s", player
                )
                continue

            assert isinstance(player["playerid"], str)
            assert isinstance(player["name"], str)
            if "modelname" in player:
                assert isinstance(player["modelname"], str)
                model = player["modelname"]
            else:
                model = None

            if search:
                if search.lower() in player["name"].lower():
                    players.append(
                        Player(
                            self,
                            player["playerid"],
                            player["name"],
                            model=model,
                        )
                    )
            else:
                players.append(
                    Player(
                        self,
                        player["playerid"],
                        player["name"],
                        model=model,
                    )
                )
        _LOGGER.debug("get_players(%s) returning players: %s", search, players)
        return players

    async def async_get_player(
        self, player_id: str | None = None, name: str | None = None
    ) -> Player | None:
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
                    assert isinstance(data["player_name"], str)
                    return Player(self, player_id, data["player_name"])
            _LOGGER.debug("Unable to find player with player_id: %s", player_id)
            return None
        if name:
            players = await self.async_get_players(name)
            if players is not None and len(players) > 0:
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

    async def async_status(self, *args: str) -> ServerStatus | dict[str, Any] | None:
        """
        Return status of current server.

        Without extra parameters the response will have type ServerStatus.

        Extra tagged parameters are added to the response dictionary.
        """
        query = ["serverstatus", "-", "-"]
        if len(args) > 0:
            query += args
        self.status = await self.async_query(*query)
        if self.status:
            if self.uuid is None and "uuid" in self.status:
                self.uuid = self.status["uuid"]
        # todo: add validation
        return self.status

    async def async_command(self, *command: str, player: str = "") -> bool:
        """Send a command to the JSON-RPC connection where no result is returned."""
        result = await self.async_query(*command, player=player)
        if result == {}:
            return True
        return False

    async def async_query(self, *command: str, player: str = "") -> QueryResult | None:
        """Return result of query on the JSON-RPC connection."""
        auth = (
            None
            if self._username is None or self._password is None
            else aiohttp.BasicAuth(self._username, self._password)
        )
        url = f"{self._prefix}://{self.host}:{self.port}/jsonrpc.js"
        query_data = json.dumps(
            {"id": "1", "method": "slim.request", "params": [player, command]}
        )

        _LOGGER.debug("URL: %s Data: %s", url, query_data)

        if self.session is None:
            raise ValueError("async_query() called with Server.session unset")

        try:
            async with async_timeout.timeout(TIMEOUT):
                response = await self.session.post(url, data=query_data, auth=auth)
                self.http_status = response.status

                if response.status != 200:
                    _LOGGER.info(
                        "Query failed, response code: %s Full message: %s",
                        response.status,
                        response,
                    )
                    return None

                result_data = await response.json()

        except aiohttp.ServerDisconnectedError as error:
            # LMS handles an unknown player by abruptly disconnecting
            if player:
                _LOGGER.info("Query run on unknown player %s", player)
            else:
                _LOGGER.error("Failed communicating with LMS(%s): %s", url, type(error))
            return None

        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            _LOGGER.error("Failed communicating with LMS(%s): %s", url, type(error))
            return None

        try:
            result = result_data["result"]
            if not isinstance(result, dict):
                _LOGGER.error("Received invalid response: %s", result)
                return None
            return result
        except KeyError:
            _LOGGER.error("Received invalid response: %s", result_data)
        return None

    async def async_browse(
        self,
        category: str,
        limit: int | None = None,
        browse_id: tuple[str, str] | None = None,
    ) -> QueryResult | None:
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
        browse: dict[str, Any] = {}
        search = f"{browse_id[0]}:{browse_id[1]}" if browse_id else None

        if (
            category in ["playlist", "album", "artist", "genre", "title", "favorite"]
            and search
        ):
            browse["title"] = await self.async_get_category_title(category, search)
        else:
            browse["title"] = category.title()

        if category in ["playlist", "album", "title"]:
            item_type = "titles"
        elif category in ["genre"]:
            item_type = "artists"
        elif category in ["artist"]:
            item_type = "albums"
        else:
            item_type = category

        items = await self.async_get_category(item_type, limit, search)

        browse["items"] = items
        if category == "title" and items is not None:
            browse["title"] = items[0]["title"]
        return browse

    async def async_get_count(self, category: str) -> int:
        """Return number of category in database."""
        query = [category]
        if category == "favorites":
            query.append("items")
        query.extend(["0", "1"])
        result = await self.async_query(*query)
        if result and "count" in result and isinstance(result["count"], int):
            return result["count"]
        return 0

    async def async_query_category(
        self, category: str, limit: int | None = None, search: str | None = None
    ) -> list[QueryResult] | None:
        """Return list of entries in category, optionally filtered by search string."""
        if not limit:
            limit = await self.async_get_count(category)

        if category == "titles" and search and "playlist_id" in search:
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
            query.extend(["0", f"{limit}"])
            if search:
                query.append(search)

        # add command-specific suffixes
        if query[0] == "albums":
            query.append("tags:jla")
        elif query[0] == "titles":
            query.append("sort:albumtrack")
            query.append("tags:ju")
        elif query[0] == "favorites":
            query.append("want_url:1")

        result = await self.async_query(*query)
        if not result or "count" not in result or not isinstance(result["count"], int):
            return None

        if result["count"] == 0:
            return None

        items = None
        try:
            if query[0] == "favorites":
                items = result["loop_loop"]  # strange, but what LMS returns
            elif category == "titles" and query[0] == "playlists":
                items = result["playlisttracks_loop"]
            else:
                items = result[f"{category}_loop"]
            assert isinstance(items, list)
            for item in items:
                if query[0] == "favorites":
                    if item["isaudio"] != 1 and item["hasitems"] != 1:
                        continue
                    item["title"] = item.pop("name")
                    if (
                        "url" in item
                        and isinstance(item["url"], str)
                        and item["url"].startswith("db:album.title")
                    ):
                        album_id = await self.async_get_album_id_from_url(item["url"])
                        if album_id is not None:
                            item["album_id"] = album_id
                    if "image" in item:
                        image = item.pop("image")
                        if isinstance(image, str):
                            if image_url := self.generate_image_url(image):
                                item["image_url"] = image_url
                                if track_id := self.get_track_id_from_image_url(
                                    image_url
                                ):
                                    item["artwork_track_id"] = track_id
                elif query[0] != "favorites":
                    item["title"] = item.pop(category[:-1])

                if "artwork_track_id" in item and isinstance(
                    item["artwork_track_id"], int
                ):
                    if image_url := self.generate_image_url_from_track_id(
                        item["artwork_track_id"]
                    ):
                        item["image_url"] = image_url
            return items

        except KeyError:
            if not items:
                _LOGGER.error("Could not find results loop for category %s", category)
                _LOGGER.error("Got result %s", result)
            else:
                raise

        return None

    async def async_get_category(
        self, category: str, limit: int | None = None, search: str | None = None
    ) -> list[dict[str, Any]] | None:
        """Update cache of library category if needed and return result."""
        if (
            category not in ["artists", "albums", "titles", "genres"]
            or search is not None
        ):
            return await self.async_query_category(category, limit, search)

        status = await self.async_status()
        if status is None:
            _LOGGER.debug("No category information available because status is None")
            return None
        cached_category = self._browse_cache.get(category)
        if "lastscan" in status and cached_category is not None:
            if int(status["lastscan"]) <= cached_category[0]:
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
        if status and status.get("lastscan") is not None:
            self._browse_cache[category] = (int(status["lastscan"]), limit, result)
        else:
            self._browse_cache[category] = None

        if limit and result:
            return result[:limit]
        return result

    async def async_get_category_title(
        self, category: str, search: str | None
    ) -> str | None:
        """
        Search of the category name corresponding to a title.
        """
        result = await self.async_query_category(f"{category}s", 50, search=search)
        if result and len(result) > 0:
            return str(result[0]["title"])
        return None

    def generate_image_url_from_track_id(self, track_id: int) -> str:
        """Generate an image url using a track id."""
        return self.generate_image_url(f"/music/{track_id}/cover.jpg")

    def generate_image_url(self, image_url: str) -> str:
        """Add the appropriate base_url to a relative image_url."""
        base_url = f"{self._prefix}://"
        if self._username and self._password:
            base_url += urllib.parse.quote(self._username, safe="")
            base_url += ":"
            base_url += urllib.parse.quote(self._password, safe="")
            base_url += "@"

        base_url += f"{self.host}:{self.port}/"

        return urllib.parse.urljoin(base_url, image_url)

    def get_track_id_from_image_url(self, image_url: str) -> str | None:
        """Get a track id from an image url."""
        match = re.search(r"^(?:/?)music/([^/]+)/cover.*", image_url)
        if match:
            return match.group(1)
        return None

    async def async_get_album_id_from_url(self, url: str) -> int | None:
        """Find the album_id from a favorites url."""
        album_seach_string = urllib.parse.unquote(url)[15:].split("&contributor.name=")
        album_title = album_seach_string[0]
        album_contributor = (
            album_seach_string[1] if len(album_seach_string) > 1 else None
        )

        albums = await self.async_get_category("albums")
        if albums and len(albums) > 0:
            for album in albums:
                if album["title"] == album_title:
                    if album_contributor:
                        if album["artist"] == album_contributor:
                            return int(album["id"])
                    else:
                        return int(album["id"])
                else:
                    continue
        return None
