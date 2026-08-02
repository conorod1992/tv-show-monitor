"""Tests for coordinated updates and persistent preservation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.tv_show_monitor.api import TVMazeError
from custom_components.tv_show_monitor.const import ConfiguredShow, LastKnownState
from custom_components.tv_show_monitor.coordinator import TVShowMonitorCoordinator


def make_coordinator(hass, shows, effects):
    client = AsyncMock()
    client.async_get_next_episode.side_effect = effects
    entry = MagicMock(entry_id="test")
    coordinator = TVShowMonitorCoordinator(hass, client, tuple(shows), 24, entry)
    coordinator._store = AsyncMock()
    return coordinator


async def test_all_shows_update_successfully(hass, severance, episode):
    other = ConfiguredShow(2, "Doctor Who", "Doctor Who")
    coordinator = make_coordinator(hass, [severance, other], [episode, None])
    data = await coordinator._async_update_data()
    assert data[216].state.episode == episode
    assert data[2].state.has_successful_value
    assert data[2].state.episode is None


async def test_one_show_failure_does_not_block_other(hass, severance, episode):
    other = ConfiguredShow(2, "Doctor Who", "Doctor Who")
    coordinator = make_coordinator(
        hass, [severance, other], [TVMazeError("HTTP 500"), episode]
    )
    data = await coordinator._async_update_data()
    assert not data[216].state.has_successful_value
    assert data[2].state.episode == episode


async def test_failed_show_retains_previous_episode(hass, severance, episode):
    coordinator = make_coordinator(hass, [severance], [TVMazeError("timeout")])
    coordinator._states[216] = LastKnownState(
        has_successful_value=True,
        episode=episode,
        last_successful_update="old",
        last_attempt_successful=True,
    )
    data = await coordinator._async_update_data()
    assert data[216].state.episode == episode
    assert data[216].state.last_successful_update == "old"
    assert data[216].state.last_attempt_successful is False
    assert data[216].state.last_error == "timeout"


async def test_failed_show_retains_previous_no_episode(hass, severance):
    coordinator = make_coordinator(hass, [severance], [TVMazeError("HTTP 404")])
    coordinator._states[216] = LastKnownState(
        has_successful_value=True, episode=None, last_successful_update="old"
    )
    data = await coordinator._async_update_data()
    assert data[216].state.has_successful_value
    assert data[216].state.episode is None
    assert data[216].state.last_attempt_successful is False


async def test_successful_no_episode_clears_old_episode(hass, severance, episode):
    coordinator = make_coordinator(hass, [severance], [None])
    coordinator._states[216] = LastKnownState(
        has_successful_value=True, episode=episode
    )
    data = await coordinator._async_update_data()
    assert data[216].state.has_successful_value
    assert data[216].state.episode is None
    assert data[216].state.last_attempt_successful is True


async def test_initial_failure_without_cache(hass, severance):
    coordinator = make_coordinator(hass, [severance], [TVMazeError("offline")])
    data = await coordinator._async_update_data()
    assert not data[216].state.has_successful_value
    assert data[216].state.last_error == "offline"


async def test_persisted_state_restored_after_restart(hass, severance, episode):
    coordinator = make_coordinator(hass, [severance], [])
    coordinator._store.async_load.return_value = {
        "shows": {
            "216": LastKnownState(
                has_successful_value=True,
                episode=episode,
                last_successful_update="saved",
            ).as_dict()
        }
    }
    await coordinator._async_setup()
    assert coordinator._states[216].episode == episode
    assert coordinator._states[216].last_successful_update == "saved"


async def test_removed_shows_are_pruned_from_persisted_storage(
    hass, severance, episode
):
    coordinator = make_coordinator(hass, [severance], [])
    coordinator._store.async_load.return_value = {
        "shows": {
            "216": LastKnownState(True, episode).as_dict(),
            "999": LastKnownState(True, episode).as_dict(),
        }
    }
    await coordinator._async_setup()
    saved = coordinator._store.async_save.call_args.args[0]
    assert set(saved["shows"]) == {"216"}


async def test_concurrent_refreshes_are_deduplicated(hass, severance, episode):
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed(_show_id):
        started.set()
        await release.wait()
        return episode

    coordinator = make_coordinator(hass, [severance], delayed)
    coordinator.data = {}
    first = asyncio.create_task(coordinator.async_request_refresh())
    await started.wait()
    second = asyncio.create_task(coordinator.async_request_refresh())
    release.set()
    await asyncio.gather(first, second)
    assert coordinator.client.async_get_next_episode.await_count == 1
    await coordinator.async_shutdown()
