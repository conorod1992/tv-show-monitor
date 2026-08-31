"""Regression tests for restart-safe episode events."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_show_monitor.api import TVMazeError
from custom_components.tv_show_monitor.const import (
    EVENT_EPISODE_AIRING,
    EVENT_EPISODE_TODAY,
    LastKnownState,
    ShowScheduleInfo,
)
from custom_components.tv_show_monitor.coordinator import (
    AIRING_EVENT_CATCH_UP_WINDOW,
    TVShowMonitorCoordinator,
    _episode_airing_key,
    _episode_today_key,
)


def make_coordinator(hass, show, schedule):
    """Build a coordinator with a fixed TVmaze schedule response."""
    client = AsyncMock()
    if isinstance(schedule, BaseException):
        client.async_get_show_schedule.side_effect = schedule
    else:
        client.async_get_show_schedule.return_value = schedule
    entry = MockConfigEntry(domain="tv_show_monitor", entry_id="test")
    coordinator = TVShowMonitorCoordinator(hass, client, (show,), 24, entry)
    coordinator._store = AsyncMock()
    return coordinator


async def test_restored_today_event_fires_even_when_startup_refresh_is_offline(
    hass, severance, episode
):
    """Use last-good persisted state to avoid losing today's event on restart."""
    today = dt_util.now().date().isoformat()
    today_episode = replace(
        episode,
        air_date=today,
        air_stamp=f"{today}T23:30:00+00:00",
    )
    coordinator = make_coordinator(hass, severance, TVMazeError("offline"))
    coordinator._store.async_load.return_value = {
        "shows": {
            "216": LastKnownState(
                has_successful_value=True,
                episode=today_episode,
                show_status="Running",
            ).as_dict()
        }
    }
    events = []
    hass.bus.async_listen(EVENT_EPISODE_TODAY, events.append)

    try:
        await coordinator._async_setup()
        await coordinator._async_update_data()
        await hass.async_block_till_done()

        key = _episode_today_key(today_episode, hass.config.time_zone)
        assert len(events) == 1
        assert coordinator._states[216].episode_today_fired_key == key
        assert coordinator._states[216].last_attempt_successful is False
        assert coordinator._states[216].last_error == "offline"
    finally:
        await coordinator.async_shutdown()


async def test_restored_today_event_does_not_repeat_when_marker_was_persisted(
    hass, severance, episode
):
    """Respect the persisted today-event marker across restart."""
    today = dt_util.now().date().isoformat()
    today_episode = replace(
        episode,
        air_date=today,
        air_stamp=f"{today}T23:30:00+00:00",
    )
    key = _episode_today_key(today_episode, hass.config.time_zone)
    coordinator = make_coordinator(
        hass,
        severance,
        ShowScheduleInfo("Running", today_episode, None),
    )
    coordinator._store.async_load.return_value = {
        "shows": {
            "216": LastKnownState(
                has_successful_value=True,
                episode=today_episode,
                show_status="Running",
                episode_today_fired_key=key,
            ).as_dict()
        }
    }
    events = []
    hass.bus.async_listen(EVENT_EPISODE_TODAY, events.append)

    try:
        await coordinator._async_setup()
        await coordinator._async_update_data()
        await hass.async_block_till_done()

        assert events == []
        assert coordinator._states[216].episode_today_fired_key == key
    finally:
        await coordinator.async_shutdown()


async def test_recent_missed_airing_is_caught_up_once_after_restart(
    hass, severance, episode
):
    """Catch up an exact airing missed during a short Home Assistant outage."""
    airing = datetime.now(UTC) - timedelta(minutes=30)
    recent_episode = replace(
        episode,
        air_date=airing.date().isoformat(),
        air_stamp=airing.isoformat(),
    )
    coordinator = make_coordinator(
        hass,
        severance,
        ShowScheduleInfo("Running", recent_episode, None),
    )
    coordinator._store.async_load.return_value = {
        "shows": {
            "216": LastKnownState(
                has_successful_value=True,
                episode=recent_episode,
                show_status="Running",
            ).as_dict()
        }
    }
    events = []
    hass.bus.async_listen(EVENT_EPISODE_AIRING, events.append)

    try:
        await coordinator._async_setup()
        await coordinator._async_update_data()
        await hass.async_block_till_done()

        key = _episode_airing_key(recent_episode)
        assert len(events) == 1
        assert events[0].data["episode_id"] == recent_episode.episode_id
        assert coordinator._states[216].episode_airing_fired_key == key
    finally:
        await coordinator.async_shutdown()


async def test_stale_missed_airing_is_not_caught_up(hass, severance, episode):
    """Do not emit exact-airing events long after they ceased to be timely."""
    airing = datetime.now(UTC) - AIRING_EVENT_CATCH_UP_WINDOW - timedelta(minutes=1)
    stale_episode = replace(
        episode,
        air_date=airing.date().isoformat(),
        air_stamp=airing.isoformat(),
    )
    coordinator = make_coordinator(
        hass,
        severance,
        ShowScheduleInfo("Running", stale_episode, None),
    )
    coordinator._store.async_load.return_value = {
        "shows": {
            "216": LastKnownState(
                has_successful_value=True,
                episode=stale_episode,
                show_status="Running",
            ).as_dict()
        }
    }
    events = []
    hass.bus.async_listen(EVENT_EPISODE_AIRING, events.append)

    try:
        await coordinator._async_setup()
        await hass.async_block_till_done()

        assert events == []
        assert coordinator._states[216].episode_airing_fired_key is None
    finally:
        await coordinator.async_shutdown()
