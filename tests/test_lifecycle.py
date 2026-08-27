"""Focused tests for show lifecycle persistence and polling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.tv_show_monitor.const import (
    ENDED_RECHECK_DAYS,
    LastKnownState,
)
from custom_components.tv_show_monitor.coordinator import _should_skip_ended_refresh


def test_recent_ended_show_without_next_episode_skips_refresh():
    now = datetime(2026, 8, 27, 22, 0, tzinfo=UTC)
    state = LastKnownState(
        has_successful_value=True,
        show_status="Ended",
        episode=None,
        last_successful_update=(now - timedelta(days=10)).isoformat(),
    )
    assert _should_skip_ended_refresh(state, now)


def test_ended_show_is_rechecked_after_monthly_interval():
    now = datetime(2026, 8, 27, 22, 0, tzinfo=UTC)
    state = LastKnownState(
        has_successful_value=True,
        show_status="Ended",
        episode=None,
        last_successful_update=(now - timedelta(days=ENDED_RECHECK_DAYS)).isoformat(),
    )
    assert not _should_skip_ended_refresh(state, now)


def test_ended_show_with_future_episode_keeps_normal_polling(episode):
    now = datetime(2026, 8, 27, 22, 0, tzinfo=UTC)
    state = LastKnownState(
        has_successful_value=True,
        show_status="Ended",
        episode=episode,
        last_successful_update=(now - timedelta(days=1)).isoformat(),
    )
    assert not _should_skip_ended_refresh(state, now)


def test_lifecycle_metadata_round_trips_through_storage(episode):
    original = LastKnownState(
        has_successful_value=True,
        episode=None,
        previous_episode=episode,
        show_status="Ended",
        ended_date="2026-05-07",
        network_name="NBC",
        web_channel_name="Peacock",
        schedule_days=("Thursday",),
        schedule_time="22:00",
        last_successful_update="2026-08-27T22:00:00+00:00",
    )
    restored = LastKnownState.from_dict(original.as_dict())
    assert restored == original
