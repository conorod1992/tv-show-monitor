"""Next-episode sensors for TV Show Monitor."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TVShowMonitorConfigEntry
from .const import NO_NEXT_EPISODE, EpisodeInfo
from .entity import TVShowMonitorEntity


async def async_setup_entry(
    hass: Any,
    entry: TVShowMonitorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one sensor for every configured show."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TVShowNextEpisodeSensor(coordinator, show) for show in coordinator.shows
    )


class TVShowNextEpisodeSensor(TVShowMonitorEntity, SensorEntity):
    """The next scheduled episode date for one show."""

    _attr_translation_key = "next_episode"

    @property
    def available(self) -> bool:
        """Remain available through failures if a last-good value exists."""
        return self.result.state.has_successful_value

    @property
    def native_value(self) -> str | None:
        """Return an ISO date, the explicit no-episode text, or unavailable."""
        state = self.result.state
        if not state.has_successful_value:
            return None
        if state.episode is None:
            return NO_NEXT_EPISODE
        return state.episode.air_date

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose show, episode, schedule and safe refresh diagnostics."""
        result = self.result
        state = result.state
        attributes: dict[str, Any] = {
            "tvmaze_show_id": result.show.tvmaze_id,
            "show_status": state.show_status,
            "last_successful_update": state.last_successful_update,
            "last_update_attempt": state.last_update_attempt,
            "last_attempt_successful": state.last_attempt_successful,
        }
        episode = state.episode
        if state.has_successful_value and episode is None:
            attributes["next_episode_found"] = False
        elif episode is not None:
            attributes.update(
                {
                    "next_episode_found": True,
                    "episode_id": episode.episode_id,
                    "episode_name": episode.name,
                    "season": episode.season,
                    "episode_number": episode.number,
                    "episode_type": episode.episode_type,
                    "air_date": episode.air_date,
                    "air_time": episode.air_time,
                    "air_stamp": episode.air_stamp,
                    "next_airing": episode.air_stamp,
                    "runtime": episode.runtime,
                    "episode_url": episode.url,
                    "show_url": result.show.show_url,
                }
            )
            days_until = _days_until(episode.air_date)
            if days_until is not None:
                attributes["days_until"] = days_until
            code = _episode_code(episode)
            if code is not None:
                attributes["episode_code"] = code

        previous = state.previous_episode
        if previous is not None:
            attributes.update(
                {
                    "previous_episode_id": previous.episode_id,
                    "previous_episode_name": previous.name,
                    "previous_season": previous.season,
                    "previous_episode_number": previous.number,
                    "previous_air_date": previous.air_date,
                    "previous_air_time": previous.air_time,
                    "previous_air_stamp": previous.air_stamp,
                    "previous_episode_url": previous.url,
                }
            )
            code = _episode_code(previous)
            if code is not None:
                attributes["previous_episode_code"] = code

        if state.last_attempt_successful is False:
            attributes["last_error"] = state.last_error
        return attributes


def _days_until(air_date: str) -> int | None:
    try:
        scheduled = date.fromisoformat(air_date)
    except ValueError:
        return None
    return (scheduled - dt_util.now().date()).days


def _episode_code(episode: EpisodeInfo) -> str | None:
    if episode.season is None or episode.number is None:
        return None
    return f"S{episode.season:02d}E{episode.number:02d}"
