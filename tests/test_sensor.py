"""Tests for TV Show Monitor sensor presentation."""

from __future__ import annotations

from unittest.mock import MagicMock

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


def test_date_state_stable_identity_attributes_and_device(severance, episode):
    sensor = make_sensor(
        severance,
        LastKnownState(
            True,
            episode,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            True,
        ),
    )
    assert sensor.native_value == "2026-10-12"
    assert sensor.unique_id == f"{DOMAIN}_216_next_episode"
    assert sensor.extra_state_attributes["episode_code"] == "S02E04"
    assert sensor.extra_state_attributes["episode_name"] == episode.name
    assert sensor.device_info["identifiers"] == {(DOMAIN, "216")}
    assert sensor.device_info["manufacturer"] == "TVmaze"


def test_no_next_episode_state(severance):
    sensor = make_sensor(
        severance, LastKnownState(True, None, "saved", "attempt", True)
    )
    assert sensor.available
    assert sensor.native_value == "No next episode found"
    assert sensor.extra_state_attributes["next_episode_found"] is False


def test_initial_unavailable_state(severance):
    sensor = make_sensor(severance, LastKnownState())
    assert not sensor.available
    assert sensor.native_value is None


def test_failed_refresh_retains_state_and_sets_diagnostics(severance, episode):
    sensor = make_sensor(
        severance,
        LastKnownState(True, episode, "saved", "latest", False, "request timed out"),
    )
    assert sensor.available
    assert sensor.native_value == episode.air_date
    attributes = sensor.extra_state_attributes
    assert attributes["episode_name"] == episode.name
    assert attributes["last_attempt_successful"] is False
    assert attributes["last_error"] == "request timed out"
