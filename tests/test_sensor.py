"""Tests for TV Show Monitor sensor presentation."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from custom_components.tv_show_monitor.const import (
    DOMAIN,
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
    assert attributes["days_until"] == 2
    assert attributes["next_airing"] == episode.air_stamp
    assert attributes["previous_episode_name"] == episode.name
    assert attributes["previous_episode_code"] == "S02E04"
    assert sensor.device_info["identifiers"] == {(DOMAIN, "216")}
    assert sensor.device_info["manufacturer"] == "TVmaze"


def test_no_next_episode_state(severance):
    sensor = make_sensor(
        severance, LastKnownState(True, None, "saved", "attempt", True)
    )
    assert sensor.available
    assert sensor.native_value == "No next episode found"
    assert sensor.entity_picture is None
    assert sensor.extra_state_attributes["next_episode_found"] is False


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
