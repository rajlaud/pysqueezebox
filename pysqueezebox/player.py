"""The pysqueezebox.Player() class."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import time as dt_time
from typing import TYPE_CHECKING, Any, Callable, TypedDict

import async_timeout

from .const import REPEAT_MODE, SHUFFLE_MODE, QueryResult

_LOGGER = logging.getLogger(__name__)

# default timeout waiting for server to communicate with player
TIMEOUT = 5

# default timeout waiting for announcement to complete.  large value to allow pausing etc..  Can be overridden
ANNOUNCE_TIMEOUT = 600

# how quickly to poll server waiting for command to reach player
POLL_INTERVAL = 0.75

# types for status query responses


class PlaylistEntry(TypedDict, total=False):
    """Typed dictionary with minimum info to be a playlist entry."""

    url: str


class Track(PlaylistEntry, total=False):
    """Extend PlaylistEntry to include other track properties."""

    title: str
    artist: str
    album: str
    type: str
    bitrate: str
    samplerate: str
    samplesize: str
    duration: str
    coverid: int
    remote_title: str
    artwork_url: str


AlarmJSON = TypedDict(
    "AlarmJSON",
    {
        "time": int,
        "dow": str,
        "enabled": str,
        "repeat": str,
        "volume": str,
        "url": str,
        "id": str,
    },
    total=False,
)

PlayerStatus = TypedDict(
    "PlayerStatus",
    {
        "alarm_next": int,
        "alarm_state": str,
        "player_connected": int,
        "power": int,
        "mode": str,
        "mixer volume": str,
        "current_title": str,
        "time": int,
        "remote": int,
        "remote_title": str,
        "playlist_cur_index": str,
        "playlist_loop": list[Track] | None,
        "remoteMeta": Track | None,
        "playlist_timestamp": float,
        "playlist_tracks": str,
        "playlist shuffle": int,
        "playlist repeat": int,
        "samplerate": str,
        "samplesize": str,
        "sync_master": str,
        "sync_slaves": str,
        "alarms_loop": list[AlarmJSON] | None,
    },
    total=False,
)

PlayerPrefs = TypedDict(
    "PlayerPrefs",
    {
        "alarmsEnabled": str,
    },
    total=False,
)

if TYPE_CHECKING:
    from .server import Server


# pylint: disable=too-many-public-methods


class Alarm(TypedDict, total=False):
    """Parameters for an alarm."""

    time: dt_time
    dow: list[int]
    enabled: bool
    repeat: bool
    volume: int
    url: str
    id: str


def _parse_alarm_params(params: Alarm) -> list[str]:
    """Take typed inputs and convert them to strings suitable for LMS."""
    parlist = []

    for key, value in params.items():
        if key == "time" and params["time"] is not None:
            time = params["time"]
            parlist.append(f"{key}:{time.hour * 3600 + time.minute * 60 + time.second}")
        if key == "dow" and params["dow"] is not None:
            dow = params["dow"]
            parlist.append(f"{key}:{','.join(map(str, dow))}")
        if key in ["enabled", "repeat"] and value is not None:
            parlist.append(f"{key}:{'1' if value else '0'}")
        if key in ["volume", "url"] and value is not None:
            parlist.append(f"{key}:{value}")
    return parlist


class Player:
    """Representation of a SqueezeBox device."""

    def __init__(
        self,
        lms: Server,
        player_id: str,
        name: str,
        status: PlayerStatus | None = None,
        model: str | None = None,
        model_type: str | None = None,
        firmware: str | None = None,
    ):
        """
        Initialize the SqueezeBox device.

        Parameters:
            lms: the Server object controlling the player (required)
            player_id: the unique identifier for the player (required)
            name: the player's name (required)
            status: status dictionary for player (optional)
            model: the player's model name (optional)
        """
        self._lms = lms
        self._id = player_id
        self._status = status if status else {}
        self._playlist_timestamp = 0
        self._playlist_tags: set[str] = set()
        self._name = name
        self._model = model
        self._model_type = model_type
        self._firmware = firmware
        self._announce_volume: int | None = None
        self._announce_timeout: int | None = None

        self._property_futures: list[dict[str, Any]] = []
        self._poll: asyncio.Task[Any] | None = None
        self._saved_state: dict[str, Any] | None = None

        self._player_prefs: PlayerPrefs = {}

        _creator = None
        _squeezelite = ", Ralph Irving & Adrian Smith"
        if model is None:
            # make typing happy
            pass
        elif model == "SqueezePlayer":
            _creator = "Stefan Hansel"
        elif model == "Squeezelite-X":
            _creator = "R G Dawson"
        elif model == "SqueezeLite" or "SqueezePlay" in model:
            _creator = "Ralph Irving & Adrian Smith"
            _squeezelite = ""
        elif model == "SqueezeLite-HA-Addon":
            _creator = "pssc"
        elif model == "RaopBridge" or model == "CastBridge":
            _creator = "philippe"
        elif model == "SB Player":
            _creator = "Wayne Tam"
        elif model == "WiiM Player":
            _creator = "LinkPlay"
        elif (
            "Squeezebox" in model
            or "Transporter" in model
            or "Slim" in model
            or "Jive" in model
        ):
            _creator = "Logitech"
        elif (
            (model == "SqueezeLite")
            or ("SqueezePlay" in model)
            or (model_type == "squeezelite")
        ):
            if firmware and "-pCP" in firmware:
                _creator = "Paul, Steen, Greg"
            else:
                # Unknown or Generic.
                _creator = "Ralph Irving & Adrian Smith"
                _squeezelite = ""
        if model_type == "squeezelite":
            _creator = (_creator or "") + _squeezelite

        self._creator = _creator
        _LOGGER.debug("Creating SqueezeBox object: %s, %s", name, player_id)

    def __repr__(self) -> str:
        """Return representation of Player object."""
        return f"Player('{self._lms}', '{self._id}', '{self._name}', {self._status})"

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._name

    @property
    def player_id(self) -> str:
        """Return the player ID, which is its MAC address."""
        return self._id

    @property
    def model(self) -> str | None:
        """Return the players model name, e.g. Squeezebox Boom"""
        return self._model

    @property
    def model_type(self) -> str | None:
        """Return the players model type, e.g. baby"""
        return self._model_type

    @property
    def firmware(self) -> str | None:
        """Return the player's firmware version if available"""
        return self._firmware

    @property
    def creator(self) -> str | None:
        """Return the player's creator if available"""
        return self._creator

    @property
    def connected(self) -> bool:
        """
        Return True if the player is connected to the LMS server.

        The API call is less useful than it sounds, because after player has
        been disconnected for a few minutes from the server, it disappears
        altogether from the API. We still return False, not None, because it
        still means the player is disconnected.
        """
        if "player_connected" in self._status:
            return self._status["player_connected"] == 1
        return False

    @property
    def power(self) -> bool | None:
        """Return the power state of the device."""
        if "power" in self._status:
            return self._status["power"] == 1
        return None

    @property
    def mode(self) -> str | None:
        """Return the mode of the device. One of play, stop, or pause."""
        return self._status.get("mode")

    @property
    def volume(self) -> int | None:
        """
        Return volume level of the Player.

        Returns integer from 0 to 100.
        LMS will return a negative integer if the volume is muted. This leads
        to inconsistent results if you later try to update the volume with
        the negative number, which is instead interpreted as a decrement.
        We return the absolute value, separating out volume from muting.
        """
        if "mixer volume" in self._status:
            return abs(int(self._status["mixer volume"]))
        return None

    @property
    def announce_volume(self) -> int | None:
        """Return volume level for announcements."""
        return self._announce_volume

    @property
    def muting(self) -> bool:
        """Return true if volume is muted."""
        if "mixer volume" in self._status:
            return str(self._status["mixer volume"]).startswith("-")
        return False

    @property
    def current_title(self) -> str | None:
        """Return title of current playing media on remote stream."""
        return self._status.get("current_title")

    @property
    def duration(self) -> int | None:
        """Return duration of current playing media in seconds."""
        return int(self.duration_float) if self.duration_float else None

    @property
    def duration_float(self) -> float | None:
        """Return duration of current playing media in floating point seconds."""
        if self.current_track and "duration" in self.current_track:
            return float(self.current_track["duration"])
        return None

    @property
    def time(self) -> int | None:
        """
        Return position of current playing media in seconds.

        The LMS API calls this "time" so we follow that convention.
        """
        return int(self.time_float) if self.time_float else None

    @property
    def time_float(self) -> float | None:
        """
        Return position of current playing media in floating point seconds.

        The LMS API calls this "time" so we follow that convention.
        """
        if "time" in self._status:
            return float(self._status["time"])
        return None

    @property
    def image_url(self) -> str:
        """Return image url of current playing media."""
        if self.current_track and "artwork_url" in self.current_track:
            # we're playing a remote stream with an artwork url
            artwork_url = self.current_track["artwork_url"]
            # some plugins generate a relative artwork_url
            if not artwork_url.startswith("http"):
                artwork_url = self._lms.generate_image_url(artwork_url)
            return artwork_url
        if self.current_track and "coverid" in self.current_track:
            return self._lms.generate_image_url_from_track_id(
                self.current_track["coverid"]
            )

        # querying a coverid without art will result in the default image
        # we use 'unknown' so that this image can be cached
        return self._lms.generate_image_url("/music/unknown/cover.jpg")

    @property
    def current_index(self) -> int | None:
        """Return the current index in the playlist."""
        if "playlist_cur_index" in self._status:
            return int(self._status["playlist_cur_index"])
        return None

    @property
    def current_track(self) -> Track | None:
        """Return playlist_loop or remoteMeta dictionary for current track."""
        try:
            return self._status["remoteMeta"]
        except KeyError:
            pass
        try:
            if self.playlist and self.current_index is not None:
                return self.playlist[self.current_index]
        except IndexError:
            pass
        return None

    @property
    def remote(self) -> bool:
        """Return true if current media is a remote stream."""
        if "remote" in self._status:
            return self._status["remote"] == 1
        return False

    @property
    def remote_title(self) -> str | None:
        """Return title of current playing media on remote stream."""
        if self.current_track and "remote_title" in self.current_track:
            return self.current_track.get("remote_title")
        return None

    @property
    def title(self) -> str | None:
        """Return title of current playing media."""
        if self.current_track:
            return self.current_track.get("title")
        return None

    @property
    def artist(self) -> str | None:
        """Return artist of current playing media."""
        if self.current_track:
            return self.current_track.get("artist")
        return None

    @property
    def album(self) -> str | None:
        """Return album of current playing media."""
        if self.current_track:
            return self.current_track.get("album")
        return None

    @property
    def content_type(self) -> str | None:
        """Return content type of current playing media."""
        if self.current_track:
            return self.current_track.get("type")
        return None

    @property
    def bitrate(self) -> str | None:
        """Return bit rate of current playing media as a string including units."""
        if self.current_track:
            return self.current_track.get("bitrate")
        return None

    @property
    def samplerate(self) -> int | None:
        """Return sample rate of current playing media in KHz, if known."""
        if self.current_track:
            samplerate = self.current_track.get("samplerate")
            return int(samplerate) if samplerate else None
        return None

    @property
    def samplesize(self) -> int | None:
        """Return sample size of current playing media in bits."""
        if self.current_track and "samplesize" in self.current_track:
            samplesize = self.current_track.get("samplesize")
            return int(samplesize) if samplesize else None
        return None

    @property
    def shuffle(self) -> str | None:
        """Return shuffle mode. May be 'none, 'song', or 'album'."""
        if "playlist shuffle" in self._status:
            return SHUFFLE_MODE[self._status["playlist shuffle"]]
        return None

    @property
    def repeat(self) -> str | None:
        """Return repeat mode. May be 'none', 'song', or 'playlist'."""
        if "playlist repeat" in self._status:
            return REPEAT_MODE[self._status["playlist repeat"]]
        return None

    @property
    def url(self) -> str | None:
        """Return the url for the currently playing media."""
        if self.current_track:
            return self.current_track.get("url")
        return None

    @property
    def playlist(self) -> list[Track] | None:
        """Return the current playlist."""
        return self._status.get("playlist_loop")

    @property
    def alarms(self) -> list[Alarm] | None:
        """Return the list of alarms."""
        result: list[Alarm] = []
        if (
            "alarms_loop" in self._status
            and self._status["alarms_loop"] is not None
            and len(self._status["alarms_loop"]) > 0
        ):
            for alarm in self._status["alarms_loop"]:
                seconds = int(alarm["time"])
                minutes, seconds = divmod(seconds, 60)
                hours, minutes = divmod(minutes, 60)
                result.append(
                    {
                        "time": dt_time(second=seconds, minute=minutes, hour=hours),
                        "dow": list(map(int, alarm["dow"].split(","))),
                        "enabled": alarm["enabled"] == "1",
                        "repeat": alarm["repeat"] == "1",
                        "volume": int(alarm["volume"]),
                        "url": alarm["url"],
                        "id": alarm["id"],
                    }
                )
            return result
        return None

    @property
    def alarms_enabled(self) -> bool:
        """Return the state of the alarms enabled player setting."""
        return self._player_prefs.get("alarmsEnabled") == "1"

    @property
    def alarm_state(self) -> str | None:
        """Return the current alarm state"""
        return self._status.get("alarm_state")

    @property
    def alarm_next(self) -> int | None:
        """Return the time stamp of the next alarm (seconds since the epoch)"""
        return self._status.get("alarm_next")

    @property
    def playlist_urls(self) -> list[PlaylistEntry] | None:
        """Return only the urls of the current playlist. Useful for comparing playlists."""
        if not self.playlist:
            return None
        return [{"url": item["url"]} for item in self.playlist]

    @property
    def playlist_tracks(self) -> int | None:
        """Return the current playlist length."""
        if "playlist_tracks" in self._status:
            return int(self._status["playlist_tracks"])
        return None

    @property
    def synced(self) -> bool:
        """Return true if currently synced."""
        return self._status.get("sync_master") is not None

    @property
    def sync_master(self) -> str | None:
        """Return the player id of the sync group master."""
        return self._status.get("sync_master")

    @property
    def sync_slaves(self) -> list[str] | None:
        """Return the player ids of the sync group slaves."""
        sync_slaves = self._status.get("sync_slaves")
        if sync_slaves is not None:
            return sync_slaves.split(",")
        return None

    @property
    def sync_group(self) -> list[str] | None:
        """Return the player ids of all players in current sync group."""
        sync_group = []
        if self.sync_slaves:
            sync_group = self.sync_slaves
        if self.sync_master:
            sync_group.append(self.sync_master)
        return sync_group

    def create_property_future(
        self,
        prop: str,
        test: Callable[[Any], bool],
        interval: float | None = POLL_INTERVAL,
    ) -> asyncio.Future[bool]:
        """
        Create a future awaiting a property value.

        prop: the property to test
        test: future satisfied when test(prop) returns true. Must accept test(None).
        interval: how often to poll, defaults to POLL_INTERVAL but may be set to None for
                  passive wait (optional)
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._property_futures.append(
            {"prop": prop, "test": test, "future": future, "interval": interval}
        )
        loop.create_task(self.async_update())
        return future

    async def _wait_for_property(self, prop: str, value: Any, timeout: float) -> bool:
        """Wait for property to hit certain state or timeout."""
        if timeout == 0:
            return True
        try:
            async with async_timeout.timeout(timeout):
                await self.create_property_future(prop, lambda x: value == x)
                return True
        except asyncio.TimeoutError:
            _LOGGER.error(
                "Timed out (%s) waiting for %s to have value %s", timeout, prop, value
            )
            return False

    async def async_command(self, *parameters: str) -> bool:
        """Send a command to the player."""
        return await self._lms.async_command(*parameters, player=self._id)

    async def async_query(
        self, *parameters: str, timeout: float = TIMEOUT
    ) -> QueryResult | None:
        """Return result of a query specific to this player."""
        return await self._lms.async_query(
            *parameters, player=self._id, timeout=timeout
        )

    async def async_update(self, add_tags: str | None = None) -> bool:
        """
        Update the current state of the player.
        Also updates the list of alarms set for this player.

        Return True if successful, False if update fails.
        """
        # cancel pending poll if we were called manually
        if self._poll and not self._poll.done():
            self._poll.cancel()

        tags = "acdIKlNorTuxQ"
        if add_tags:
            tags = "".join(set(tags + add_tags))
        response = await self.async_query(
            "status", "-", "1", f"tags:{tags}", "alarmData:1"
        )

        if response is None:
            return False

        if (
            "playlist_timestamp" in response
            and isinstance(response["playlist_timestamp"], float)
            and "playlist_tracks" in response
            and isinstance(response["playlist_tracks"], int)
        ):
            playlist_timestamp = response["playlist_timestamp"]
            if (
                playlist_timestamp > self._playlist_timestamp
                or set(tags) > self._playlist_tags
            ):
                self._playlist_timestamp = response["playlist_timestamp"]
                self._playlist_tags = set(tags)
                # poll server again for full playlist, which has either changed
                # or about which we are seeking new tags
                response = await self.async_query(
                    "status", "0", str(response["playlist_tracks"]), f"tags:{tags}"
                )

                if response is None:
                    _LOGGER.debug("Error updating status - unable to retrieve playlist")
                    return False
            else:
                response.pop("playlist_loop", None)
        else:
            # no current playlist
            self._status.update({"playlist_loop": None})

        # preserve the playlist between updates
        self._status = {"playlist_loop": self._status.get("playlist_loop")}

        # todo: validate response
        self._status.update(response)  # type: ignore

        # read alarm clock data
        # it seems, unlike playlist length, there's no way to know beforehand how many there are
        # we just do 99
        response = await self.async_query("alarms", "0", "99", "filter:all")
        if response is None:
            _LOGGER.debug("Did not receive alarm data")
            return False

        if "alarms_loop" in response:
            # todo: validate the alarm data
            self._status.update({"alarms_loop": response["alarms_loop"]})  # type: ignore
        else:
            self._status.update({"alarms_loop": None})

        # check whether the alarmsEnabled preference is set
        response = await self.async_query("playerpref", "alarmsEnabled", "?")
        if (
            response is None
            or "_p2" not in response
            or not isinstance(response["_p2"], str)
        ):
            _LOGGER.debug("Unable to retrieve alarmsEnabled preference")
        else:
            self._player_prefs["alarmsEnabled"] = response["_p2"]

        # check if any property futures have been satisfied
        property_futures = []
        interval = None
        for property_future in self._property_futures:
            if not property_future["future"].done():
                if property_future["test"](getattr(self, property_future["prop"])):
                    property_future["future"].set_result(True)
                else:
                    property_futures.append(property_future)
                    if property_future["interval"]:
                        if not interval or interval > property_future["interval"]:
                            interval = property_future["interval"]
        self._property_futures = property_futures

        # schedule poll if pending futures with polling interval
        if len(self._property_futures) > 0 and interval:
            self._poll = asyncio.create_task(self._async_poll(interval))
        return True

    async def _async_poll(self, interval: float) -> None:
        await asyncio.sleep(interval)
        asyncio.create_task(self.async_update())

    async def async_set_volume(
        self, volume: int | str, timeout: float = TIMEOUT
    ) -> bool:
        """Set volume level, range 0..100, or +/- integer."""
        if (
            isinstance(volume, str)
            and (volume.startswith("+") or volume.startswith("-"))
            or isinstance(volume, int)
            and volume < 0
        ):
            await self.async_update()
            target_volume = int(volume) + self.volume if self.volume else 0
        else:
            target_volume = int(volume)
        if not await self.async_command("mixer", "volume", str(volume)):
            return False
        return await self._wait_for_property("volume", target_volume, timeout)

    def set_announce_volume(self, volume: int | None) -> None:
        """Set the volume level for announcements."""
        self._announce_volume = volume

    def set_announce_timeout(self, timeout: int | None) -> None:
        """Set the volume level for announcements."""
        self._announce_timeout = timeout

    async def async_set_muting(self, mute: bool, timeout: float = TIMEOUT) -> bool:
        """Mute (true) or unmute (false) squeezebox."""
        mute_numeric = "1" if mute else "0"
        if not await self.async_command("mixer", "muting", mute_numeric):
            return False
        return await self._wait_for_property("muting", mute, timeout)

    async def async_toggle_pause(self, timeout: float = TIMEOUT) -> bool:
        """Send command to player to toggle play/pause."""
        await self.async_update()
        target_mode = "pause" if self.mode == "play" else "play"

        if not await self.async_command("pause"):
            return False
        return await self._wait_for_property("mode", target_mode, timeout)

    async def async_play(self, timeout: float = TIMEOUT) -> bool:
        """Send play command to player."""
        if not await self.async_command("play"):
            return False
        return await self._wait_for_property("mode", "play", timeout)

    async def async_stop(self, timeout: float = TIMEOUT) -> bool:
        """Send stop command to player."""
        return await self._async_pause_stop(["stop"], timeout)

    async def async_pause(self, timeout: float = TIMEOUT) -> bool:
        """Send pause command to player."""
        return await self._async_pause_stop(["pause", "1"], timeout)

    async def _async_pause_stop(self, cmd: list[str], timeout: float = TIMEOUT) -> bool:
        """
        Retry pause or stop command until successful or timed out.

        Necessary because a pause or stop command sent immediately after a play command will be
        silently ignored by LMS.
        """

        async def _verified_pause_stop(cmd: list[str]) -> bool:
            success = await self.async_command(*cmd)
            if success:
                return await self.async_update()
            _LOGGER.error("Failed to send command %s", cmd)
            return False

        if not await _verified_pause_stop(cmd):
            return False

        try:
            async with async_timeout.timeout(timeout):
                future = self.create_property_future("mode", lambda x: x != "play")
                while not future.done():
                    await _verified_pause_stop(cmd)
                    await asyncio.sleep(POLL_INTERVAL)
                return True
        except asyncio.TimeoutError:
            return False

    async def async_index(self, index: int | str, timeout: float = TIMEOUT) -> bool:
        """
        Change position in playlist.

        index: if an unsigned integer, change to this position. if preceded by a + or -,
               move forward or backward this many tracks. (required)
        """

        if isinstance(index, int):
            index = str(index)
        if isinstance(index, str) and (index.startswith("+") or index.startswith("-")):
            await self.async_update()
            if self.current_index is None:
                _LOGGER.error(
                    "Can't increment or decrement index when no current index exists."
                )
                return False
            target_index = self.current_index + int(index)
        else:
            target_index = int(index)

        if not await self.async_command("playlist", "index", index):
            return False
        return await self._wait_for_property("current_index", target_index, timeout)

    async def async_time(
        self, position: int | float | str, timeout: float = TIMEOUT
    ) -> bool:
        """Seek to a particular time in track."""
        if not position:
            return False

        position = float(position)

        await self.async_update()
        if self.mode not in ["play", "pause"]:
            return False

        if not await self.async_command("time", str(position)):
            return False

        try:
            async with async_timeout.timeout(timeout):
                # We have to use a fuzzy match to see if the player got the command.
                await self.create_property_future(
                    "time", lambda time: time and position <= time <= position + timeout
                )
                return True
        except asyncio.TimeoutError:
            return False

    async def async_set_power(self, power: bool, timeout: float = TIMEOUT) -> bool:
        """Turn on or off squeezebox."""
        power_numeric = "1" if power else "0"
        if not await self.async_command("power", power_numeric):
            return False
        return await self._wait_for_property("power", power, timeout)

    async def async_load_url(
        self,
        url: str,
        cmd: str = "load",
        timeout: float = TIMEOUT,
    ) -> bool:
        """
        Play a specific track by url.

        cmd: "play" or "load" - replace current playlist (default)
        cmd: "play_now" - adds to current spot in playlist
        cmd: "insert" - adds next in playlist
        cmd: "add" - adds to end of playlist
        cmd: "announce" - interrupts the current playlist then resumes it after this track
        """
        index = self.current_index or 0

        if cmd == "announce":
            await self.async_save_player_state()
            if self._announce_volume:
                await self.async_set_volume(self._announce_volume)

        if cmd in ["play_now", "insert", "add"] and self.playlist_urls:
            await self.async_update()
            target_playlist: list[PlaylistEntry] = self.playlist_urls or []
            if cmd == "add":
                target_playlist.append({"url": url})
            else:
                if cmd == "insert":
                    index += 1
                target_playlist.insert(index, {"url": url})
        else:
            target_playlist = [{"url": url}]

        if cmd == "play_now":
            await self.async_load_playlist(target_playlist)
            await self.async_index(index)
        else:
            if cmd != "announce":
                _ret = await self.async_command("playlist", cmd, url)
            else:
                _ret = await self.async_command("playlist", "play", url, "Announcement")
            if not _ret:
                return False

        result = await self._wait_for_property(
            "playlist_urls", target_playlist, timeout
        )

        if cmd == "announce":
            await self.async_set_repeat("none")
            await self._wait_for_property(
                "mode",
                "stop",
                self._announce_timeout if self._announce_timeout else ANNOUNCE_TIMEOUT,
            )
            await self.async_restore_player_state()

        return result

    async def async_load_playlist(
        self,
        playlist_ref: Sequence[PlaylistEntry],
        cmd: str = "load",
    ) -> bool:
        """
        Play a playlist, of the sort return by the Player.playlist property.

        playlist: an array of dictionaries, which must each have a key
                  called "url." (required)
        cmd: "play" or "load" - replace current playlist (default)
        cmd: "insert" - adds next in playlist
        cmd: "add" - adds to end of playlist
        """
        if not playlist_ref:
            return False

        success = True

        # we are going to pop the list below, so we need to copy it
        playlist = list(playlist_ref)

        # remove non-playable items from the playlist
        playlist = [item for item in playlist if item.get("url")]

        if cmd == "insert":
            for item in reversed(playlist):
                if not await self.async_load_url(item["url"], cmd):
                    success = False
            return success

        if cmd in ["play", "load"]:
            if not await self.async_load_url(playlist.pop(0)["url"], "play"):
                success = False

        for item in playlist:
            if not await self.async_load_url(item["url"], "add"):
                success = False

        return success

    async def async_add_alarm(
        self,
        time: dt_time,
        dow: list[int] = [0, 1, 2, 3, 4, 5, 6],
        enabled: bool = False,
        repeat: bool = True,
        volume: int | None = None,
        url: str | None = None,
    ) -> str | None:
        """
        Creates a new alarm clock on this player.
        Follows the description on http(s)://<server>:<port>/html/docs/cli-api.html?player=#alarm

        Parameters
        ----------
        time : datetime.time
            Mandatory time of alarm
        dow : list[int]
            Day Of Week. 0 is Sunday, 1 is Monday, etc. up to 6 being Saturday.
            Default: [0, 1, 2, 3, 4, 5, 6]
        enabled : bool
            Default: False
        repeat : bool
            Set to True to make this a repeated alarm, False otherwise.
            Default: True
        volume : int
            Volume for this alarm, valid values are 0-100, defaults to default alarm volume
        url: str
            URL for the alarm playlist, defaults to current playlist

        Returns
        -------
        alarm_id: str
            ID of newly created alarm, None if not successfull
        """

        params: Alarm = {
            "time": time,
            "dow": dow,
            "enabled": enabled,
            "repeat": repeat,
        }

        if volume is not None:
            params["volume"] = volume
        if url is not None:
            params["url"] = url
        parlist = _parse_alarm_params(params)
        response = await self.async_query("alarm", "add", *parlist)
        if response is None:
            _LOGGER.debug("Alarm with params %s could not be added", parlist)
            return None
        else:
            _LOGGER.debug("Response when adding alarm: %s", response)
            if "id" in response and isinstance(response["id"], str):
                return response["id"]
            return None

    async def async_update_alarm(
        self,
        alarm_id: str,
        time: dt_time | None = None,
        dow: list[int] | None = None,
        enabled: bool | None = None,
        repeat: bool | None = None,
        volume: int | None = None,
        url: str | None = None,
    ) -> str | None:
        """
        Updates an existing alarm clock
        Follows the description on http(s)://<server>:<port>/html/docs/cli-api.html?player=#alarm

        Parameters
        ----------
        alarm_id : str
            Mandatory id of the alarm to update
        time : datetime.time
            `time` of alarm
        dow : list of ints
            Day Of Week. 0 is Sunday, 1 is Monday, etc. up to 6 being Saturday.
            Default: [0, 1, 2, 3, 4, 5, 6].
        enabled : bool
            Default: False
        repeat : bool
            True if this is a repeated alarm, False if it runs only one time.
            Default: True
        volume : int
            Volume for this alarm, valid values are 0-100, defaults to default alarm volume
        url: str
            URL for the alarm playlist, defaults to current playlist

        Returns
        -------
        alarm_id: str
            ID of updated alarm, None if not successful
        """
        params: Alarm = {}
        if time is not None:
            params["time"] = time
        if dow is not None:
            params["dow"] = dow
        if enabled is not None:
            params["enabled"] = enabled
        if repeat is not None:
            params["repeat"] = repeat
        if volume is not None:
            params["volume"] = volume
        if url is not None:
            params["url"] = url
        parlist = _parse_alarm_params(params)
        parlist.append(f"id:{alarm_id}")
        response = await self.async_query("alarm", "update", *parlist)
        if response is None:
            _LOGGER.debug("Alarm with id %s could not be updated", alarm_id)
            return None
        else:
            _LOGGER.debug("Response when updating alarm: %s", alarm_id)
            if "id" in response and isinstance(response["id"], str):
                return response["id"]
            return None

    async def async_delete_alarm(self, alarm_id: str) -> bool:
        """
        Deletes an existing alarm clock
        Follows the description on http(s)://<server>:<port>/html/docs/cli-api.html?player=#alarm

        Parameters
        ----------
        alarm_id : str
            Mandatory id of the alarm to delete

        Returns
        -------
        bool
            True if successful, False otherwise

        """
        response = await self.async_query("alarm", "delete", f"id:{alarm_id}")
        if response is None:
            _LOGGER.debug("Alarm with id %s could not be deleted", alarm_id)
            return False
        return True

    async def async_set_shuffle(self, shuffle: str, timeout: float = TIMEOUT) -> bool:
        """Enable/disable shuffle mode."""
        if shuffle in SHUFFLE_MODE:
            shuffle_int = SHUFFLE_MODE.index(shuffle)
            if not await self.async_command("playlist", "shuffle", str(shuffle_int)):
                return False
            return await self._wait_for_property("shuffle", shuffle, timeout)
        raise ValueError(f"Invalid shuffle mode: {shuffle}")

    async def async_set_repeat(self, repeat: str, timeout: float = TIMEOUT) -> bool:
        """Enable/disable repeat."""
        if repeat in REPEAT_MODE:
            repeat_int = REPEAT_MODE.index(repeat)
            if not await self.async_command("playlist", "repeat", str(repeat_int)):
                return False
            return await self._wait_for_property("repeat", repeat, timeout)
        raise ValueError(f"Invalid repeat mode: {repeat}")

    async def async_clear_playlist(self, timeout: float = TIMEOUT) -> bool:
        """Send the media player the command for clear playlist."""
        if not await self.async_command("playlist", "clear"):
            return False
        return await self._wait_for_property("playlist", None, timeout)

    async def async_sync(
        self, other_player: "Player" | str, timeout: float = TIMEOUT
    ) -> bool:
        """
        Add another Squeezebox player to this player's sync group.

        If the other player is a member of a sync group, it will leave the
        current sync group without asking.

        Other player may be a player object, or a player_id.
        """
        if isinstance(other_player, Player):
            other_player_id = other_player.player_id
        else:
            other_player_id = other_player

        if not other_player_id:
            raise RuntimeError(
                "async_sync called without other_player or other_player_id"
            )

        if not await self.async_command("sync", other_player_id):
            return False

        await self.async_update()
        try:
            async with async_timeout.timeout(timeout):
                await self.create_property_future(
                    "sync_group", lambda sync_group: other_player_id in sync_group
                )
                return True
        except asyncio.TimeoutError:
            return False

    async def async_unsync(self, timeout: float = TIMEOUT) -> bool:
        """Unsync this Squeezebox player."""
        if not await self.async_command("sync", "-"):
            return False
        return await self._wait_for_property("sync_group", [], timeout)

    async def async_browse(
        self,
        category: str,
        limit: int | None = None,
        browse_id: tuple[str, str] | None = None,
        search_query: str | None = None,
    ) -> QueryResult | None:
        """
        Browse the music library.

        See Server.async_browse for parameters.
        """
        return await self._lms.async_browse(
            category,
            limit=limit,
            browse_id=browse_id,
            player_id=self._id,
            search_query=search_query,
        )

    def generate_image_url_from_track_id(self, track_id: int) -> str:
        """Return the image url for a track_id."""
        return self._lms.generate_image_url_from_track_id(track_id)

    def generate_image_url(self, image_url: str) -> str:
        """Return the image url."""
        return self._lms.generate_image_url(image_url)

    async def async_save_player_state(self) -> None:
        """Save the current player state for later restoration."""
        self._saved_state = {
            "repeat": self.repeat,
            "time": self.time,
            "mode": self.mode,
            "power": self.power,
            "mixer_volume": self.volume,
            "shuffle": self.shuffle,
        }
        await self.async_command(
            "playlist",
            "save",
            f"tempplaylist_{self.player_id.replace(':', '')}",
        )

    async def async_restore_player_state(self) -> None:
        """Restore the player state to the saved state."""
        if not self._saved_state:
            _LOGGER.debug("No saved state to restore")
            return

        await self.async_command(
            "playlist",
            "resume",
            f"tempplaylist_{self.player_id.replace(':', '')}",
            f"noplay:{0 if self._saved_state['mode'] == 'play' else 1}",
            "wipePlaylist",
        )

        await self.async_set_repeat(self._saved_state["repeat"])
        await self.async_set_shuffle(self._saved_state["shuffle"])
        await self.async_set_volume(self._saved_state["mixer_volume"])
        await self.async_time(self._saved_state["time"])
        await self.async_set_power(self._saved_state["power"])

        self._saved_state = None

    async def async_set_alarms_enabled(self, enabled: bool) -> bool:
        """Enable or disable alarms on this player."""
        if not await self.async_command(
            "playerpref", "alarmsEnabled", "1" if enabled else "0"
        ):
            return False
        return await self._wait_for_property("alarms_enabled", enabled, TIMEOUT)
