import aiohttp
import asyncio
import pytest
from time import sleep
from pysqueezebox import Server, Player
SERVER = '192.168.2.2'
PLAYER = 'Tape'
TEST_URIS = [
'file:///mnt/squeezebox/music/best_quality/The%20Who/A%20Quick%20One/02%20Boris%20the%20Spider.mp3',
'file:///mnt/squeezebox/music/best_quality/The%20Beatles/Revolver/06%20Yellow%20Submarine.flac',
'file:///mnt/squeezebox/music/best_quality/Bob%20Marley%20&%20The%20Wailers/Catch%20A%20Fire/04%20Stop%20That%20Train.flac'
            ]

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


def compare_playlists(a, b):
    """compare two playlists checking only the urls"""
    if len(a) == len(b):
        for x in range(0, len(a)):
            if a[x]["url"] != b[x]["url"]:
                return False
        return True
    return False

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def lms(event_loop):
    print("Created LMS session")
    async with aiohttp.ClientSession() as session:
        lms = Server(session, SERVER)
        yield lms


@pytest.fixture(scope="module")
async def player(lms):
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
    broken_player = Player(lms, "NOT A PLAYER ID", "Bogus player")
    yield broken_player


async def test_get_players(lms):
    players = await lms.async_get_players()
    for player in players:
        assert isinstance(player, Player)


async def test_get_player(lms, player):
    """tests get_player; SERVER must have at least one player active"""
    test_player_a = await lms.async_get_player(name=player.name)
    test_player_b = await lms.async_get_player(player_id=player.player_id)
    assert test_player_a.name == test_player_b.name
    assert test_player_a.player_id == test_player_b.player_id

    # test that we properly return None when there is no matching player
    test_player_none = await lms.async_get_player(name="NO SUCH PLAYER")
    assert test_player_none is None
    test_player_none = await lms.async_get_player(player_id="NO SUCH ID")
    assert test_player_none is None


async def test_player_properties(player):
    """tests each property; SERVER must have at least one player active"""
    for p in dir(Player):
        prop = getattr(Player, p)
        if isinstance(prop, property):
            print(f"{p}: {prop.fget(player)}")


async def test_async_query(player):
    """tests Player async_query()"""
    # test query with result
    result = await player.async_query("status")
    assert result["mode"] in ["play", "pause", "stop"]
    # test query with no result
    result = await player.async_query("pause", "1")
    assert result
    # test bad query
    result = await player.async_query("invalid")
    assert not result


async def test_player_power(player, broken_player):
    """tests Player power controls"""
    assert await player.async_set_power(True)
    assert not await broken_player.async_set_power(True)
    await player.async_update()
    assert player.power
    assert await player.async_set_power(False)
    await player.async_update()
    assert not player.power
    assert await player.async_set_power(True)
    await player.async_update()
    assert player.power


async def test_player_muting(player, broken_player):
    """test Player muting controls"""
    assert await player.async_update()
    muting = player.muting
    assert await player.async_set_muting(True)
    await player.async_update()
    assert player.muting
    assert await player.async_set_muting(True)
    await player.async_update()
    assert player.muting
    assert await player.async_set_muting(False)
    await player.async_update()
    assert not player.muting
    await player.async_set_muting(muting)
    assert not await broken_player.async_set_muting(True)


async def test_player_volume(player, broken_player):
    """test Player volume controls"""
    assert await player.async_update()
    muting = player.muting
    assert await player.async_set_muting(True)
    assert await player.async_update()
    vol = player.volume
    assert 0 <= vol <= 100

    new_vol = vol + 5 if vol < 50 else vol - 5
    assert await player.async_set_volume(new_vol)
    await player.async_update()
    assert player.volume == new_vol

    assert await player.async_set_volume(vol)
    assert await player.async_set_muting(muting)

    assert not await broken_player.async_set_volume(new_vol)


async def test_player_play_pause(player, broken_player):
    """test play and pause controls"""
    assert await player.async_update()
    power = player.power
    if not power:
        assert await player.async_set_power(True)
    mode = player.mode

    assert await player.async_play()
    assert not await broken_player.async_play()
    sleep(2)
    await player.async_update()
    assert player.mode == "play"

    assert await player.async_play()
    sleep(2)
    await player.async_update()
    assert player.mode == "play"

    assert await player.async_pause()
    assert not await broken_player.async_pause()
    sleep(2)
    await player.async_update()
    assert player.mode == "pause"

    assert await player.async_pause()
    sleep(2)
    await player.async_update()
    assert player.mode == "pause"

    assert await player.async_toggle_pause()
    assert not await broken_player.async_toggle_pause()
    sleep(2)
    await player.async_update()
    assert player.mode == "play"

    if mode != "play":
        await player.async_pause()

    if not power:
        await player.async_set_power(False)


async def test_player_load_url_and_index(player, broken_player):
    await player.async_update()
    playlist = player.playlist

    assert await player.async_clear_playlist()
    assert not await broken_player.async_clear_playlist()
    await player.async_update()
    assert player.playlist is None

    assert await player.async_load_url(TEST_URIS[0], "play")
    await player.async_update()
    assert len(player.playlist) == 1
    assert player.current_track["url"] == TEST_URIS[0]
    assert await player.async_load_url(TEST_URIS[1], "play")
    await player.async_update()
    assert len(player.playlist) == 1
    assert player.current_track["url"] == TEST_URIS[1]

    assert await player.async_load_url(TEST_URIS[0], "add")
    assert await player.async_load_url(TEST_URIS[1], "add")
    assert not await broken_player.async_load_url(TEST_URIS[0], "add")
    await player.async_update()
    assert len(player.playlist) == 3

    assert await player.async_index(0)
    await player.async_update()
    current_track = player.current_track
    assert await player.async_index("+1")
    await player.async_update()
    next_track = player.current_track
    assert current_track != next_track
    assert await player.async_index("-1")
    await player.async_update()
    assert current_track == player.current_track
    assert not await broken_player.async_index(0)

    assert await player.async_load_url(TEST_URIS[2], "insert")
    assert not await broken_player.async_load_url(TEST_URIS[2], "insert")
    await player.async_index("+1")
    await player.async_update()
    assert player.current_track["url"] == TEST_URIS[2]

    await player.async_clear_playlist()
    if playlist:
        await player.async_load_playlist(playlist, "add")


async def test_player_playlist(player, broken_player):
    await player.async_update()
    playlist = player.playlist

    assert await player.async_clear_playlist()
    test_playlist = [{"url": TEST_URIS[0]}, {"url": TEST_URIS[1]}]
    await player.async_update()
    assert player.playlist is None

    assert await player.async_load_playlist(test_playlist, "add")
    assert not await broken_player.async_load_playlist(test_playlist, "add")
    await player.async_update()
    assert compare_playlists(test_playlist, player.playlist)

    assert await player.async_load_playlist(reversed(test_playlist), "play")
    assert not await broken_player.async_load_playlist(test_playlist, "play")
    await player.async_update()
    assert compare_playlists(list(reversed(test_playlist)), player.playlist)

    await player.async_index(0)
    assert await player.async_load_playlist(test_playlist, "insert")
    assert not await broken_player.async_load_playlist(test_playlist, "insert")
    await player.async_update()
    current_playlist = test_playlist[1:] + test_playlist + test_playlist[:1]
    assert compare_playlists(current_playlist, player.playlist)

    await player.async_clear_playlist()
    await player.async_load_playlist(playlist, "add")


async def test_player_shuffle(player, broken_player):
    await player.async_update()
    shuffle_mode = player.shuffle

    for mode in ['none', 'song', 'album']:
        assert await player.async_set_shuffle(mode)
        assert not await broken_player.async_set_shuffle(mode)
        await player.async_update()
        assert mode == player.shuffle

    await player.async_set_shuffle(shuffle_mode)


async def test_player_repeat(player, broken_player):
    await player.async_update()
    repeat_mode = player.repeat

    for mode in ['none', 'song', 'playlist']:
        assert await player.async_set_repeat(mode)
        assert not await broken_player.async_set_repeat(mode)
        await player.async_update()
        assert mode == player.repeat

    await player.async_set_repeat(repeat_mode)


async def test_player_sync(lms, broken_player):
    players = await lms.async_get_players()
    muting = {}
    sync_master = {}

    test_master = players[0]
    for player in players:
        # mute all players
        await player.async_update()
        muting[player.player_id] = player.muting
        await player.async_set_muting(True)
        sync_master[player.player_id] = player.sync_master
        if player.synced:
            assert await player.async_unsync()
            await player.async_update()
            assert not player.synced
        assert await player.async_sync(test_master)
        await player.async_update()
        assert test_master.player_id in player.sync_group
        assert await player.async_unsync()
        await player.async_update()
        assert not player.synced
        assert await player.async_sync(test_master.player_id)
        await player.async_update()
        assert test_master.player_id in player.sync_group

    for player in players:
        await player.async_unsync()

    for player in players:
        if player in sync_master:
            player.async_sync(sync_master[player.player_id])
        await player.async_set_muting(muting[player.player_id])
