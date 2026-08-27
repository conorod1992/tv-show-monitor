"""Tests for TV Show Monitor sensor presentation."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.tv_show_monitor.const import (
    DOMAIN,
    MISSING_SHOW_404_THRESHOLD,
    LastKnownState,
    ShowUpdateResult,
)
from custom_components.tv_show_monitor.sensor import TVShowNextEpisodeSensor


def make_sensor(severance, state):
    coordinator = MagicMock()
    coordinator.data = {216: ShowUpdateResult(severance, state)}
    coordinator.async_add_listener.return_value = lambda: None
    return TVShowNextEpisodeSensor(coordinator, severance)


def test_date_state_stable_identity_attributes_device_and_artwork(severance, episode):
    sensor = make_sensor(
        severance,
        LastKnownState(
            True,
            episode,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            True,
            show_status="Running",
            previous_episode=episode,
            show_image_url="https://static.tvmaze.test/severance-medium.jpg",
            network_name="Apple TV+",
            schedule_days=("Friday",),
            schedule_time="09:00",
        ),
    )
    with patch(
        "custom_components.tv_show_monitor.sensor.dt_util.now",
        return_value=datetime(2026, 10, 10, tzinfo=UTC),
    ):
        attributes = sensor.extra_state_attributes
    assert sensor.native_value == "2026-10-12"
    assert sensor.unique_id == f"{DOMAIN}_216_next_episode"
    assert sensor.entity_picture == "https://static.tvmaze.test/severance-medium.jpg"
    assert attributes["episode_code"] == "S02E04"
    assert attributes["episode_name"] == episode.name
    assert attributes["show_status"] == "Running"
    assert attributes["network"] == "Apple TV+"
    assert attributes["schedule_days"] == ["Friday"]
    assert attributes["schedule_time"] == "09:00"
    assert attributes["days_until"] == 2
    assert attributes["next_airing"] == episode.air_stamp
    assert attributes["previous_episode_name"] == episode.name
    assert attributes["previous_episode_code"] == "S02E04"
    assert attributes["consecutive_not_found"] == 0
    assert attributes["missing_from_tvmaze"] is False
    assert sensor.device_info["identifiers"] == {(DOMAIN, "216")}
    assert sensor.device_info["manufacturer"] == "TVmaze"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Running", "No next episode scheduled"),
        ("Ended", "Ended"),
        ("In Development", "In Development"),
        ("To Be Determined", "To Be Determined"),
        (None, "No next episode found"),
    ],
)
def test_no_next_episode_state_reflects_show_status(severance, status, expected):
    sensor = make_sensor(
        severance,
        LastKnownState(
            True,
            None,
            "saved",
            "attempt",
            True,
            show_status=status,
        ),
    )
    assert sensor.available
    assert sensor.native_value == expected
    assert sensor.extra_state_attributes["next_episode_found"] is False


def test_ended_show_exposes_final_episode_context(severance, episode):
    sensor = make_sensor(
        severance,
        LastKnownState(
            has_successful_value=True,
            episode=None,
            show_status="Ended",
            previous_episode=episode,
            ended_date="2026-05-07",
            network_name="NBC",
            schedule_days=("Thursday",),
            schedule_time="22:00",
        ),
    )
    attributes = sensor.extra_state_attributes
    assert sensor.native_value == "Ended"
    assert attributes["ended_date"] == "2026-05-07"
    assert attributes["network"] == "NBC"
    assert attributes["final_episode_id"] == episode.episode_id
    assert attributes["final_episode_name"] == episode.name
    assert attributes["final_episode_code"] == "S02E04"
    assert attributes["final_episode_air_date"] == episode.air_date


def test_initial_unavailable_state(severance):
    sensor = make_sensor(severance, LastKnownState())
    assert not sensor.available
    assert sensor.native_value is None
    assert sensor.entity_picture is None


def test_failed_refresh_retains_state_and_sets_diagnostics(severance, episode):
    sensor = make_sensor(
        severance,
        LastKnownState(
            True,
            episode,
            "saved",
            "latest",
            False,
            "request timed out",
            show_image_url="https://static.tvmaze.test/severance-medium.jpg",
        ),
    )
    assert sensor.available
    assert sensor.native_value == episode.air_date
    assert sensor.entity_picture == "https://static.tvmaze.test/severance-medium.jpg"
    attributes = sensor.extra_state_attributes
    assert attributes["episode_name"] == episode.name
    assert attributes["last_attempt_successful"] is False
    assert attributes["last_error"] == "request timed out"


def test_persistent_not_found_marks_sensor_unavailable_but_retains_data(
    severance, episode
):
    sensor = make_sensor(
        severance,
        LastKnownState(
            True,
            episode,
            "saved",
            "latest",
            False,
            "TVmaze resource not found",
            show_image_url="https://static.tvmaze.test/severance-medium.jpg",
            consecutive_not_found=MISSING_SHOW_404_THRESHOLD,
        ),
    )
    assert not sensor.available
    assert sensor.native_value == episode.air_date
    assert sensor.entity_picture == "https://static.tvmaze.test/severance-medium.jpg"
    attributes = sensor.extra_state_attributes
    assert attributes["consecutive_not_found"] == MISSING_SHOW_404_THRESHOLD
    assert attributes["missing_from_tvmaze"] is True
