"""Tests for coordinated updates and persistent preservation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.tv_show_monitor.api import TVMazeError, TVMazeNotFoundError
from custom_components.tv_show_monitor.const import (
    EVENT_SCHEDULE_CHANGED,
    MISSING_SHOW_404_THRESHOLD,
    ConfiguredShow,
    LastKnownState,
    ShowScheduleInfo,
)
from custom_components.tv_show_monitor.coordinator import (
    MAX_CONCURRENT_REQUESTS,
    TVShowMonitorCoordinator,
)


def make_coordinator(hass, shows, effects):
    client = AsyncMock()
    if callable(effects):

        async def schedule_effect(show_id):
            value = await effects(show_id)
            return ShowScheduleInfo("Running", value, None)

        client.async_get_show_schedule.side_effect = schedule_effect
    else:
        client.async_get_show_schedule.side_effect = [
            effect
            if isinstance(effect, BaseException)
            else ShowScheduleInfo("Running", effect, None)
            for effect in effects
        ]
    entry = MagicMock(entry_id="test")
    coordinator = TVShowMonitorCoordinator(hass, client, tuple(shows), 24, entry)
    coordinator._store = AsyncMock()
    return coordinator


async def test_all_shows_update_successfully(hass, severance, episode):
    other = ConfiguredShow(2, "Doctor Who", "Doctor Who")
    coordinator = make_coordinator(hass, [severance, other], [episode, None])
    data = await coordinator._async_update_data()
    assert data[216].state.episode == episode
    assert data[216].state.show_status == "Running"
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
        show_status="Running",
        previous_episode=episode,
    )
    data = await coordinator._async_update_data()
    assert data[216].state.episode == episode
    assert data[216].state.previous_episode == episode
    assert data[216].state.show_status == "Running"
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


async def test_persistent_404s_create_repair_and_retain_last_good(
    hass, severance, episode
):
    coordinator = make_coordinator(
        hass,
        [severance],
        [TVMazeNotFoundError("missing")] * MISSING_SHOW_404_THRESHOLD,
    )
    coordinator._states[216] = LastKnownState(
        has_successful_value=True,
        episode=episode,
        last_successful_update="old",
    )
    with patch(
        "custom_components.tv_show_monitor.coordinator.async_create_missing_show_issue"
    ) as create_issue:
        for expected_count in range(1, MISSING_SHOW_404_THRESHOLD + 1):
            data = await coordinator._async_update_data()
            assert data[216].state.episode == episode
            assert data[216].state.consecutive_not_found == expected_count
    create_issue.assert_called_once_with(hass, "test", severance)


async def test_transient_failure_does_not_reset_not_found_counter(
    hass, severance, episode
):
    coordinator = make_coordinator(hass, [severance], [TVMazeError("timeout")])
    coordinator._states[216] = LastKnownState(
        has_successful_value=True,
        episode=episode,
        consecutive_not_found=2,
    )
    data = await coordinator._async_update_data()
    assert data[216].state.consecutive_not_found == 2


async def test_success_after_404s_resets_counter_and_clears_repair(
    hass, severance, episode
):
    coordinator = make_coordinator(hass, [severance], [episode])
    coordinator._states[216] = LastKnownState(
        has_successful_value=True,
        episode=episode,
        consecutive_not_found=MISSING_SHOW_404_THRESHOLD,
    )
    with patch(
        "custom_components.tv_show_monitor.coordinator.async_delete_missing_show_issue"
    ) as delete_issue:
        data = await coordinator._async_update_data()
    assert data[216].state.consecutive_not_found == 0
    assert data[216].state.last_attempt_successful is True
    delete_issue.assert_called_once_with(hass, "test", 216)


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
                show_status="Running",
                previous_episode=episode,
                consecutive_not_found=2,
            ).as_dict()
        }
    }
    await coordinator._async_setup()
    assert coordinator._states[216].episode == episode
    assert coordinator._states[216].previous_episode == episode
    assert coordinator._states[216].show_status == "Running"
    assert coordinator._states[216].last_successful_update == "saved"
    assert coordinator._states[216].consecutive_not_found == 2


async def test_persisted_missing_state_recreates_repair(hass, severance, episode):
    coordinator = make_coordinator(hass, [severance], [])
    coordinator._store.async_load.return_value = {
        "shows": {
            "216": LastKnownState(
                has_successful_value=True,
                episode=episode,
                consecutive_not_found=MISSING_SHOW_404_THRESHOLD,
            ).as_dict()
        }
    }
    with patch(
        "custom_components.tv_show_monitor.coordinator.async_create_missing_show_issue"
    ) as create_issue:
        await coordinator._async_setup()
    create_issue.assert_called_once_with(hass, "test", severance)


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


async def test_storage_load_failure_does_not_overwrite_cache(hass, severance):
    coordinator = make_coordinator(hass, [severance], [])
    coordinator._store.async_load.side_effect = OSError("read failed")
    await coordinator._async_setup()
    coordinator._store.async_save.assert_not_awaited()


async def test_initial_success_does_not_emit_schedule_event(hass, severance, episode):
    coordinator = make_coordinator(hass, [severance], [episode])
    events = []
    hass.bus.async_listen(EVENT_SCHEDULE_CHANGED, events.append)
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert events == []


async def test_newly_scheduled_episode_emits_event(hass, severance, episode):
    coordinator = make_coordinator(hass, [severance], [episode])
    coordinator._states[216] = LastKnownState(has_successful_value=True, episode=None)
    events = []
    hass.bus.async_listen(EVENT_SCHEDULE_CHANGED, events.append)
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["change_type"] == "scheduled"
    assert events[0].data["tvmaze_show_id"] == 216
    assert events[0].data["new_episode_id"] == episode.episode_id


async def test_rescheduled_episode_emits_event(hass, severance, episode):
    moved = replace(
        episode,
        air_date="2026-10-13",
        air_stamp="2026-10-13T21:00:00+00:00",
    )
    coordinator = make_coordinator(hass, [severance], [moved])
    coordinator._states[216] = LastKnownState(
        has_successful_value=True, episode=episode
    )
    events = []
    hass.bus.async_listen(EVENT_SCHEDULE_CHANGED, events.append)
    await coordinator._async_update_data()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["change_type"] == "rescheduled"
    assert events[0].data["old_air_date"] == episode.air_date
    assert events[0].data["new_air_date"] == moved.air_date


async def test_refresh_concurrency_is_bounded(hass, episode):
    shows = tuple(
        ConfiguredShow(index, f"Show {index}", f"Show {index}")
        for index in range(1, MAX_CONCURRENT_REQUESTS * 2 + 2)
    )
    current = 0
    max_seen = 0
    release = asyncio.Event()

    async def delayed(_show_id):
        nonlocal current, max_seen
        current += 1
        max_seen = max(max_seen, current)
        if current == MAX_CONCURRENT_REQUESTS:
            release.set()
        await release.wait()
        await asyncio.sleep(0)
        current -= 1
        return episode

    coordinator = make_coordinator(hass, shows, delayed)
    data = await coordinator._async_update_data()
    assert len(data) == len(shows)
    assert max_seen == MAX_CONCURRENT_REQUESTS


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
    assert coordinator.client.async_get_show_schedule.await_count == 1
    await coordinator.async_shutdown()
