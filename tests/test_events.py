"""Tests for TV Show Monitor Home Assistant events."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_show_monitor.const import (
    EVENT_EPISODE_AIRING,
    EVENT_EPISODE_TODAY,
    EVENT_STATUS_CHANGED,
    LastKnownState,
    ShowScheduleInfo,
)
from custom_components.tv_show_monitor.coordinator import (
    TVShowMonitorCoordinator,
    _episode_airing_key,
    _schedule_change_type,
)


def make_coordinator(hass, show, schedule):
    """Build a coordinator with a fixed TVmaze schedule response."""
    client = AsyncMock()
    client.async_get_show_schedule.return_value = schedule
    entry = MockConfigEntry(domain="tv_show_monitor", entry_id="test")
    coordinator = TVShowMonitorCoordinator(hass, client, (show,), 24, entry)
    coordinator._store = AsyncMock()
    return coordinator


async def test_episode_today_fires_once_when_episode_is_today(hass, severance, episode):
    today = dt_util.now().date().isoformat()
    today_episode = replace(
        episode,
        air_date=today,
        air_stamp=f"{today}T12:00:00+00:00",
    )
    coordinator = make_coordinator(
        hass,
        severance,
        ShowScheduleInfo("Running", today_episode, None),
    )
    events = []
    hass.bus.async_listen(EVENT_EPISODE_TODAY, events.append)

    try:
        await coordinator._async_update_data()
        await coordinator._async_update_data()
        await hass.async_block_till_done()

        assert len(events) == 1
        assert events[0].data["show_name"] == "Severance"
        assert events[0].data["episode_id"] == today_episode.episode_id
        assert events[0].data["episode_code"] == "S02E04"
    finally:
        await coordinator.async_shutdown()


async def test_episode_airing_fires_once(hass, severance, episode):
    coordinator = make_coordinator(
        hass,
        severance,
        ShowScheduleInfo("Running", episode, None),
    )
    coordinator._states[216] = LastKnownState(
        has_successful_value=True,
        episode=episode,
        show_status="Running",
        network_name="Apple TV+",
    )
    key = _episode_airing_key(episode)
    assert key is not None
    events = []
    hass.bus.async_listen(EVENT_EPISODE_AIRING, events.append)

    await coordinator._async_fire_episode_airing(severance, key)
    await coordinator._async_fire_episode_airing(severance, key)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["network"] == "Apple TV+"
    assert coordinator._states[216].episode_airing_fired_key == key


async def test_status_change_emits_event(hass, severance):
    coordinator = make_coordinator(
        hass,
        severance,
        ShowScheduleInfo("Ended", None, None),
    )
    coordinator._states[216] = LastKnownState(
        has_successful_value=True,
        episode=None,
        show_status="Running",
    )
    events = []
    hass.bus.async_listen(EVENT_STATUS_CHANGED, events.append)

    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        "tvmaze_show_id": 216,
        "show_name": "Severance",
        "old_status": "Running",
        "new_status": "Ended",
    }


def test_normal_episode_progression_is_not_a_schedule_change(episode):
    old = replace(
        episode,
        air_date="2026-10-12",
        air_stamp="2026-10-12T20:00:00+00:00",
        number=4,
    )
    new = replace(
        episode,
        episode_id=12346,
        air_date="2026-10-19",
        air_stamp="2026-10-19T20:00:00+00:00",
        number=5,
    )

    assert _schedule_change_type(old, new, datetime(2026, 10, 13, tzinfo=UTC)) is None


def test_aired_episode_disappearing_is_not_schedule_cleared(episode):
    old = replace(
        episode,
        air_date="2026-10-12",
        air_stamp="2026-10-12T20:00:00+00:00",
    )

    assert _schedule_change_type(old, None, datetime(2026, 10, 13, tzinfo=UTC)) is None


def test_future_episode_disappearing_is_schedule_cleared(episode):
    assert (
        _schedule_change_type(episode, None, datetime(2026, 10, 1, tzinfo=UTC))
        == "schedule_cleared"
    )


def test_future_episode_replacement_remains_a_schedule_change(episode):
    new = replace(
        episode,
        episode_id=54321,
        number=5,
        air_date="2026-10-19",
        air_stamp="2026-10-19T20:00:00+00:00",
    )
    now = datetime(2026, 10, 1, tzinfo=UTC)

    assert _schedule_change_type(episode, new, now) == "next_episode_changed"
