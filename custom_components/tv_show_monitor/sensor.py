"""Next-episode sensors for TV Show Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TVShowMonitorConfigEntry
from .const import NO_NEXT_EPISODE
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
        """Expose episode details and safe refresh diagnostics."""
        result = self.result
        state = result.state
        attributes: dict[str, Any] = {
            "tvmaze_show_id": result.show.tvmaze_id,
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
                    "runtime": episode.runtime,
                    "episode_url": episode.url,
                    "show_url": result.show.show_url,
                }
            )
            if episode.season is not None and episode.number is not None:
                attributes["episode_code"] = (
                    f"S{episode.season:02d}E{episode.number:02d}"
                )
        if state.last_attempt_successful is False:
            attributes["last_error"] = state.last_error
        return attributes
