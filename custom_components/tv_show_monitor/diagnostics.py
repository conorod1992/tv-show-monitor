"""Sanitised diagnostics for TV Show Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TVShowMonitorConfigEntry
from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_HOURS,
    MISSING_SHOW_404_THRESHOLD,
    VERSION,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TVShowMonitorConfigEntry
) -> dict[str, Any]:
    """Return safe config-entry diagnostics without raw payloads."""
    coordinator = entry.runtime_data.coordinator
    return {
        "integration_version": VERSION,
        "poll_interval_hours": entry.options.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_HOURS
        ),
        "shows": [
            {
                "canonical_name": result.show.canonical_name,
                "tvmaze_id": result.show.tvmaze_id,
                "show_status": result.state.show_status,
                "next_episode_id": result.state.episode.episode_id
                if result.state.episode
                else None,
                "previous_episode_id": result.state.previous_episode.episode_id
                if result.state.previous_episode
                else None,
                "has_persisted_successful_value": result.state.has_successful_value,
                "consecutive_not_found": result.state.consecutive_not_found,
                "missing_from_tvmaze": (
                    result.state.consecutive_not_found >= MISSING_SHOW_404_THRESHOLD
                ),
                "last_successful_update": result.state.last_successful_update,
                "last_update_attempt": result.state.last_update_attempt,
                "last_attempt_successful": result.state.last_attempt_successful,
                "last_error": result.state.last_error,
            }
            for result in coordinator.data.values()
        ],
    }
