"""
The following tests check the pysqueezebox.Player module while mocking I/O.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, call, patch

import pytest
from pysqueezebox import Player, Server

# pylint: disable=C0103
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio


async def test_repr() -> None:
    """Test the string representation of a Player."""
    mock_server = Server(None, "test")
    test_player = Player(mock_server, "00:11:22:33:44:55", "Test Player")
    # pylint: disable=eval-used
    test_player2 = eval(repr(test_player))
    assert repr(test_player) == repr(test_player2)


async def test_image_url() -> None:
    """Test creating image urls."""
    mock_server = Server(None, "192.168.1.1", username="test#", password="~/.$password")
    player = Player(mock_server, "00:11:22:33:44:55", "Test Player")
    assert (
        player.image_url
        == "http://test%23:~%2F.%24password@192.168.1.1:9000/music/unknown/cover.jpg"
    )


async def test_wait() -> None:
    """Test player._wait_for_property()."""
    with patch.object(Player, "async_update", AsyncMock()) as mock_update:
        mock_server = AsyncMock(autospec=Server)
        mock_player = Player(mock_server, "00:11:22:33:44:55", "Test Player")
        await mock_player._wait_for_property("player_id", "wrong one", 0)
        mock_update.assert_not_called()

        assert not await mock_player._wait_for_property(
            "player_id", "55:44:33:22:11:00", 0.1
        )
        mock_update.assert_called_once()


async def test_verified_pause() -> None:
    """Test player._verified_pause_stop."""
    with patch.object(
        Player, "async_command", AsyncMock(return_val=True)
    ) as mock_command, patch.object(
        Player, "async_update", AsyncMock(return_val=True)
    ) as mock_update, patch.object(
        Player, "mode", "play"
    ):
        mock_server = AsyncMock(autospec=Server)
        mock_player = Player(mock_server, "11:22:33:44:55", "Test Player")
        assert not await mock_player.async_pause(timeout=0.1)
        mock_command.assert_has_calls(
            [call("pause", "1"), call("pause", "1")], any_order=True
        )
        mock_update.assert_called()


async def test_overlapping_announcements_restore_once() -> None:
    """Test that overlapping announcements save and restore the state only once."""
    announcement_done = asyncio.Event()

    async def fake_wait(prop: str, value: Any, timeout: float) -> bool:
        if prop == "mode":
            await announcement_done.wait()
        return True

    with patch.object(
        Player, "async_command", AsyncMock(return_value=True)
    ), patch.object(Player, "_wait_for_property", side_effect=fake_wait), patch.object(
        Player, "async_set_repeat", AsyncMock(return_value=True)
    ), patch.object(
        Player, "async_save_player_state", AsyncMock()
    ) as mock_save, patch.object(
        Player, "async_restore_player_state", AsyncMock()
    ) as mock_restore:
        mock_server = AsyncMock(autospec=Server)
        mock_player = Player(mock_server, "00:11:22:33:44:55", "Test Player")

        first = asyncio.create_task(mock_player.async_load_url("first", "announce"))
        await asyncio.sleep(0)
        second = asyncio.create_task(mock_player.async_load_url("second", "announce"))
        await asyncio.sleep(0)

        # The second announcement must not save the first one as the state to
        # restore, and nothing is restored while an announcement is playing.
        mock_save.assert_called_once()
        mock_restore.assert_not_called()

        announcement_done.set()
        assert await first
        assert await second
        mock_save.assert_called_once()
        mock_restore.assert_called_once()


async def test_failed_announcement_restores_state() -> None:
    """Test that a failed announcement restores the state and a later one saves it."""
    with patch.object(
        Player, "async_command", AsyncMock(return_value=False)
    ) as mock_command, patch.object(
        Player, "_wait_for_property", AsyncMock(return_value=True)
    ), patch.object(
        Player, "async_set_repeat", AsyncMock(return_value=True)
    ), patch.object(
        Player, "async_save_player_state", AsyncMock()
    ) as mock_save, patch.object(
        Player, "async_restore_player_state", AsyncMock()
    ) as mock_restore:
        mock_server = AsyncMock(autospec=Server)
        mock_player = Player(mock_server, "00:11:22:33:44:55", "Test Player")

        assert not await mock_player.async_load_url("broken", "announce")
        mock_save.assert_called_once()
        mock_restore.assert_called_once()

        mock_command.return_value = True
        assert await mock_player.async_load_url("working", "announce")
        assert mock_save.call_count == 2
        assert mock_restore.call_count == 2
