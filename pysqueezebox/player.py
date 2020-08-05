"""The pysqueezebox.Player() class."""
import asyncio
import logging
import urllib

import async_timeout

from .const import REPEAT_MODE, SHUFFLE_MODE

_LOGGER = logging.getLogger(__name__)

# default timeout waiting for server to communicate with player
TIMEOUT = 5

# how quickly to poll server waiting for command to reach player
POLL_INTERVAL = 0.75


# pylint: disable=too-many-public-methods
class Player:
    """Representation of a SqueezeBox device."""

    def __init__(self, lms, player_id, name, status=None):
        """
        Initialize the SqueezeBox device.

        Parameters:
            lms: the Server object controlling the player (required)
            player_id: the unique identifier for the player (required)
            name: the player's name (required)
            status: status dictionary for player (optional)
        """
        self._lms = lms
        self._id = player_id
        self._status = status if status else {}
        self._playlist_timestamp = 0
        self._playlist_tags = None
        self._name = name

        self._property_futures = []
        self._poll = None

        _LOGGER.debug("Creating SqueezeBox object: %s, %s", name, player_id)

    def __repr__(self):
        """Return representation of Player object."""
        return f"Player('{self._lms}', '{self._id}', '{self._name}', {self._status})"

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def player_id(self):
        """Return the player ID, which is its MAC address."""
        return self._id

    @property
    def connected(self):
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
    def power(self):
        """Return the power state of the device."""
        if "power" in self._status:
            return self._status["power"] == 1
        return None

    @property
    def mode(self):
        """Return the mode of the device. One of play, stop, or pause."""
        return self._status.get("mode")

    @property
    def volume(self):
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
    def muting(self):
        """Return true if volume is muted."""
        if "mixer volume" in self._status:
            return str(self._status["mixer volume"]).startswith("-")
        return False

    @property
    def current_title(self):
        """Return title of current playing media on remote stream."""
        return self._status.get("current_title")

    @property
    def duration(self):
        """Return duration of current playing media in seconds."""
        return int(self.duration_float) if self.duration_float else None

    @property
    def duration_float(self):
        """Return duration of current playing media in floating point seconds."""
        if self.current_track and "duration" in self.current_track:
            return float(self.current_track["duration"])
        return None

    @property
    def time(self):
        """
        Return position of current playing media in seconds.

        The LMS API calls this "time" so we follow that convention.
        """
        return int(self.time_float) if self.time_float else None

    @property
    def time_float(self):
        """
        Return position of current playing media in floating point seconds.

        The LMS API calls this "time" so we follow that convention.
        """
        if "time" in self._status:
            return float(self._status["time"])
        return None

    @property
    def image_url(self):
        """Return image url of current playing media."""
        if self.current_track and "artwork_url" in self.current_track:
            # we're playing a remote stream with an artwork url
            image_url = self.current_track["artwork_url"]
        elif self.current_track and "coverid" in self.current_track:
            image_url = f"/music/{self.current_track['coverid']}/cover.jpg"
        else:
            # querying a coverid without art will result in the default image
            # we use 'unknown' so that this image can be cached
            image_url = "/music/unknown/cover.jpg"

        # pylint: disable=protected-access
        if self._lms._username:
            base_url = "http://{username}:{password}@{server}:{port}/".format(
                username=self._lms._username,
                password=self._lms._password,
                server=self._lms.host,
                port=self._lms.port,
            )
        else:
            base_url = "http://{server}:{port}/".format(
                server=self._lms.host, port=self._lms.port
            )

        url = urllib.parse.urljoin(base_url, image_url)

        return url

    @property
    def current_index(self):
        """Return the current index in the playlist."""
        if "playlist_cur_index" in self._status:
            return int(self._status["playlist_cur_index"])
        return None

    @property
    def current_track(self):
        """Return playlist_loop or remoteMeta dictionary for current track."""
        try:
            return self._status["remoteMeta"]
        except KeyError:
            pass
        try:
            return self._status["playlist_loop"][self.current_index]
        except (KeyError, IndexError):
            pass
        return None

    @property
    def remote(self):
        """Return true if current media is a remote stream."""
        if "remote" in self._status:
            return self._status["remote"] == 1
        return None

    @property
    def remote_title(self):
        """Return title of current playing media on remote stream."""
        if self.current_track and "remote_title" in self.current_track:
            return self.current_track.get("remote_title")
        return None

    @property
    def title(self):
        """Return title of current playing media."""
        if self.current_track:
            return self.current_track.get("title")
        return None

    @property
    def artist(self):
        """Return artist of current playing media."""
        if self.current_track:
            return self.current_track.get("artist")
        return None

    @property
    def album(self):
        """Return album of current playing media."""
        if self.current_track:
            return self.current_track.get("album")
        return None

    @property
    def content_type(self):
        """Return content type of current playing media."""
        if self.current_track:
            return self.current_track.get("type")
        return None

    @property
    def bitrate(self):
        """Return bit rate of current playing media."""
        if self.current_track:
            return self.current_track.get("bitrate")
        return None

    @property
    def samplerate(self):
        """Return sample rate of current playing media."""
        if self.current_track:
            return self.current_track.get("samplerate")
        return None

    @property
    def samplesize(self):
        """Return sample size of current playing media."""
        if self.current_track:
            return self.current_track.get("samplesize")
        return None

    @property
    def shuffle(self):
        """Return shuffle mode. May be 'none, 'song', or 'album'."""
        if "playlist shuffle" in self._status:
            return SHUFFLE_MODE[self._status["playlist shuffle"]]
        return None

    @property
    def repeat(self):
        """Return repeat mode. May be 'none', 'song', or 'playlist'."""
        if "playlist repeat" in self._status:
            return REPEAT_MODE[self._status["playlist repeat"]]
        return None

    @property
    def url(self):
        """Return the url for the currently playing media."""
        if self.current_track:
            return self.current_track.get("url")
        return None

    @property
    def playlist(self):
        """Return the current playlist."""
        return self._status.get("playlist_loop")

    @property
    def playlist_urls(self):
        """Return only the urls of the current playlist. Useful for comparing playlists."""
        if not self.playlist:
            return None
        return [{"url": item["url"]} for item in self.playlist]

    @property
    def playlist_tracks(self):
        """Return the current playlist length."""
        return self._status.get("playlist_tracks")

    @property
    def synced(self):
        """Return true if currently synced."""
        return self._status.get("sync_master")

    @property
    def sync_master(self):
        """Return the player id of the sync group master."""
        return self._status.get("sync_master")

    @property
    def sync_slaves(self):
        """Return the player ids of the sync group slaves."""
        if self._status.get("sync_slaves"):
            return self._status.get("sync_slaves").split(",")
        return None

    @property
    def sync_group(self):
        """Return the player ids of all players in current sync group."""
        sync_group = []
        if self.sync_slaves:
            sync_group = self.sync_slaves
        if self.sync_master:
            sync_group.append(self.sync_master)
        return sync_group

    def create_property_future(self, prop, test, interval=POLL_INTERVAL):
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

    async def _wait_for_property(self, prop, value, timeout):
        """Wait for property to hit certain state or timeout."""
        if timeout == 0:
            return True
        try:
            with async_timeout.timeout(timeout):
                return await self.create_property_future(prop, lambda x: value == x)
        except asyncio.TimeoutError:
            _LOGGER.error("Timed out waiting for %s to have value %s", prop, value)
            return False

    async def async_query(self, *parameters):
        """Return result of a query specific to this player."""
        return await self._lms.async_query(*parameters, player=self._id)

    async def async_update(self, add_tags=None):
        """
        Update the current state of the player.

        Return True if successful, False if update fails.
        """
        tags = "acdIKlNorTux"
        if add_tags:
            tags = "".join(set(tags + add_tags))
        response = await self.async_query("status", "-", "1", f"tags:{tags}")

        if response is False:
            return False

        if "playlist_timestamp" in response and "playlist_tracks" in response:
            if (
                response["playlist_timestamp"] > self._playlist_timestamp
                or set(tags) > self._playlist_tags
            ):
                self._playlist_timestamp = response["playlist_timestamp"]
                self._playlist_tags = set(tags)
                # poll server again for full playlist, which has either changed
                # or about which we are seeking new tags
                response = await self.async_query(
                    "status", "0", response["playlist_tracks"], f"tags:{tags}"
                )
            else:
                response.pop("playlist_loop", None)
        else:
            # no current playlist
            self._status.update({"playlist_loop": None})

        # preserve the playlist between updates
        self._status = {"playlist_loop": self._status.get("playlist_loop")}
        self._status.update(response)

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
        if self._poll and not self._poll.done():
            self._poll.cancel()
        if len(self._property_futures) > 0 and interval:

            async def _poll(interval):
                await asyncio.sleep(interval)
                await self.async_update()

            self._poll = asyncio.create_task(_poll(interval))
        return True

    async def async_set_volume(self, volume, timeout=TIMEOUT):
        """Set volume level, range 0..100, or +/- integer."""
        if isinstance(volume, str) and (
            volume.startswith("+") or volume.startswith("-")
        ):
            await self.async_update()
            target_volume = self.volume + int(volume)
        else:
            target_volume = int(volume)
        if not await self.async_query("mixer", "volume", volume):
            return False
        return await self._wait_for_property("volume", target_volume, timeout)

    async def async_set_muting(self, mute, timeout=TIMEOUT):
        """Mute (true) or unmute (false) squeezebox."""
        mute_numeric = "1" if mute else "0"
        if not await self.async_query("mixer", "muting", mute_numeric):
            return False
        return await self._wait_for_property("muting", mute, timeout)

    async def async_toggle_pause(self, timeout=TIMEOUT):
        """Send command to player to toggle play/pause."""
        await self.async_update()
        target_mode = "pause" if self.mode == "play" else "play"

        if not await self.async_query("pause"):
            return False
        return await self._wait_for_property("mode", target_mode, timeout)

    async def async_play(self, timeout=TIMEOUT):
        """Send play command to player."""
        if not await self.async_query("play"):
            return False
        return await self._wait_for_property("mode", "play", timeout)

    async def async_stop(self, timeout=TIMEOUT):
        """Send stop command to player."""
        return await self._async_pause_stop(["stop"], timeout)

    async def async_pause(self, timeout=TIMEOUT):
        """Send pause command to player."""
        return await self._async_pause_stop(["pause", "1"], timeout)

    async def _async_pause_stop(self, cmd, timeout=TIMEOUT):
        """
        Retry pause or stop command until successful or timed out.

        Necessary because a pause or stop command sent immediately after a play command will be
        silently ignored by LMS.
        """

        async def _verified_pause_stop(cmd):
            success = await self.async_query(*cmd)
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

    async def async_index(self, index, timeout=TIMEOUT):
        """
        Change position in playlist.

        index: if an integer, change to this position. if preceded by a + or -,
               move forward or backward this many tracks. (required)
        """
        if isinstance(index, str) and (index.startswith("+") or index.startswith("-")):
            await self.async_update()
            target_index = self.current_index + int(index)
        else:
            target_index = int(index)

        if not await self.async_query("playlist", "index", index):
            return False
        return await self._wait_for_property("current_index", target_index, timeout)

    async def async_time(self, position, timeout=TIMEOUT):
        """
        Seek to a particular time in track.
        """
        if not position:
            return False

        await self.async_update()
        if self.mode not in ["play", "pause"]:
            return False

        if not await self.async_query("time", position):
            return False

        try:
            with async_timeout.timeout(timeout):
                # We have to use a fuzzy match to see if the player got the command.
                await self.create_property_future(
                    "time", lambda time: time and position <= time <= position + timeout
                )
                return True
        except asyncio.TimeoutError:
            return False

    async def async_set_power(self, power, timeout=TIMEOUT):
        """Turn on or off squeezebox."""
        power_numeric = "1" if power else "0"
        if not await self.async_query("power", power_numeric):
            return False
        return await self._wait_for_property("power", power, timeout)

    async def async_load_url(self, url, cmd="load", timeout=TIMEOUT):
        """
        Play a specific track by url.

        cmd: "play" or "load" - replace current playlist (default)
        cmd: "insert" - adds next in playlist
        cmd: "add" - adds to end of playlist
        """
        if cmd in ["insert", "add"] and self.playlist:
            await self.async_update()
            target_playlist = self.playlist_urls
            if cmd == "add":
                target_playlist.append({"url": url})
            else:
                target_playlist.insert(self.current_index + 1, {"url": url})
        else:
            target_playlist = [{"url": url}]

        if not await self.async_query("playlist", cmd, url):
            return False
        return await self._wait_for_property("playlist_urls", target_playlist, timeout)

    async def async_load_playlist(self, playlist_ref, cmd="load"):
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

    async def async_set_shuffle(self, shuffle, timeout=TIMEOUT):
        """Enable/disable shuffle mode."""
        if shuffle in SHUFFLE_MODE:
            shuffle_int = SHUFFLE_MODE.index(shuffle)
            if not await self.async_query("playlist", "shuffle", shuffle_int):
                return False
            return await self._wait_for_property("shuffle", shuffle, timeout)

    async def async_set_repeat(self, repeat, timeout=TIMEOUT):
        """Enable/disable repeat."""
        if repeat in REPEAT_MODE:
            repeat_int = REPEAT_MODE.index(repeat)
            if not await self.async_query("playlist", "repeat", repeat_int):
                return False
            return await self._wait_for_property("repeat", repeat, timeout)

    async def async_clear_playlist(self, timeout=TIMEOUT):
        """Send the media player the command for clear playlist."""
        if not await self.async_query("playlist", "clear"):
            return False
        return await self._wait_for_property("playlist", None, timeout)

    async def async_sync(self, other_player, timeout=TIMEOUT):
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

        if not await self.async_query("sync", other_player_id):
            return False

        await self.async_update()
        try:
            with async_timeout.timeout(timeout):
                await self.create_property_future(
                    "sync_group", lambda sync_group: other_player_id in sync_group
                )
                return True
        except asyncio.TimeoutError:
            return False

    async def async_unsync(self, timeout=TIMEOUT):
        """Unsync this Squeezebox player."""
        if not await self.async_query("sync", "-"):
            return False
        await self._wait_for_property("sync_group", [], timeout)
