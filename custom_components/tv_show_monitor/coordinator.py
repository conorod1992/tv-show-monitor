"""Coordinator with per-show failure isolation and persistent last-good state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import TVMazeClient, TVMazeError, TVMazeNotFoundError
from .const import (
    DOMAIN,
    ENDED_RECHECK_DAYS,
    EVENT_SCHEDULE_CHANGED,
    MISSING_SHOW_404_THRESHOLD,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    ConfiguredShow,
    EpisodeInfo,
    LastKnownState,
    ShowUpdateResult,
)
from .repairs import async_create_missing_show_issue, async_delete_missing_show_issue

_LOGGER = logging.getLogger(__name__)
MAX_CONCURRENT_REQUESTS = 5


class TVShowMonitorCoordinator(DataUpdateCoordinator[dict[int, ShowUpdateResult]]):
    """Fetch all shows in one cycle while isolating individual failures."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TVMazeClient,
        shows: tuple[ConfiguredShow, ...],
        poll_interval_hours: int,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(hours=poll_interval_hours),
            always_update=False,
        )
        self.client = client
        self.shows = shows
        self._entry_id = config_entry.entry_id
        self._states: dict[int, LastKnownState] = {}
        self._store: Store[dict[str, object]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{config_entry.entry_id}"
        )

    async def _async_setup(self) -> None:
        """Restore valid state and prune deliberately removed shows."""
        try:
            stored = await self._store.async_load() or {}
        except Exception as err:  # Storage backends can raise implementation errors.
            _LOGGER.error("Unable to load TV Show Monitor persistent state: %s", err)
            return

        raw_states = stored.get("shows", {})
        if isinstance(raw_states, dict):
            for show in self.shows:
                raw = raw_states.get(str(show.tvmaze_id))
                if isinstance(raw, dict):
                    try:
                        state = LastKnownState.from_dict(raw)
                    except KeyError, TypeError, ValueError:
                        _LOGGER.warning(
                            "Ignoring invalid persisted state for TVmaze show ID %s",
                            show.tvmaze_id,
                        )
                    else:
                        self._states[show.tvmaze_id] = state
                        if state.consecutive_not_found >= MISSING_SHOW_404_THRESHOLD:
                            async_create_missing_show_issue(
                                self.hass, self._entry_id, show
                            )
        await self._async_save()

    async def _async_update_data(self) -> dict[int, ShowUpdateResult]:
        """Refresh due shows, preserving last-good state on errors."""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        now = datetime.now(UTC)
        await asyncio.gather(
            *(
                self._async_refresh_show(show, semaphore, now)
                for show in self.shows
                if not _should_skip_ended_refresh(
                    self._states.get(show.tvmaze_id, LastKnownState()), now
                )
            )
        )
        await self._async_save()
        return {
            show.tvmaze_id: ShowUpdateResult(
                show, self._states.get(show.tvmaze_id, LastKnownState())
            )
            for show in self.shows
        }

    async def _async_refresh_show(
        self,
        show: ConfiguredShow,
        semaphore: asyncio.Semaphore,
        now: datetime,
    ) -> None:
        """Refresh one show while respecting the per-cycle concurrency limit."""
        async with semaphore:
            attempt = now.isoformat()
            previous = self._states.get(show.tvmaze_id, LastKnownState())
            try:
                schedule = await self.client.async_get_show_schedule(show.tvmaze_id)
            except TVMazeNotFoundError as err:
                error = _safe_error(err)
                not_found_count = previous.consecutive_not_found + 1
                _LOGGER.warning(
                    "TVmaze show ID %s was not found (%s/%s)",
                    show.tvmaze_id,
                    not_found_count,
                    MISSING_SHOW_404_THRESHOLD,
                )
                self._states[show.tvmaze_id] = replace(
                    previous,
                    last_update_attempt=attempt,
                    last_attempt_successful=False,
                    last_error=error,
                    consecutive_not_found=not_found_count,
                )
                if not_found_count >= MISSING_SHOW_404_THRESHOLD:
                    async_create_missing_show_issue(self.hass, self._entry_id, show)
            except TVMazeError as err:
                error = _safe_error(err)
                _LOGGER.warning(
                    "Refresh failed for TVmaze show ID %s: %s", show.tvmaze_id, error
                )
                self._states[show.tvmaze_id] = replace(
                    previous,
                    last_update_attempt=attempt,
                    last_attempt_successful=False,
                    last_error=error,
                )
            except (KeyError, TypeError, ValueError) as err:
                error = _safe_error(err)
                _LOGGER.warning(
                    "Unable to parse refresh for TVmaze show ID %s: %s",
                    show.tvmaze_id,
                    error,
                )
                self._states[show.tvmaze_id] = replace(
                    previous,
                    last_update_attempt=attempt,
                    last_attempt_successful=False,
                    last_error=error,
                )
            except Exception:  # Keep one unexpected client failure isolated per show.
                _LOGGER.exception(
                    "Unexpected refresh failure for TVmaze show ID %s",
                    show.tvmaze_id,
                )
                self._states[show.tvmaze_id] = replace(
                    previous,
                    last_update_attempt=attempt,
                    last_attempt_successful=False,
                    last_error="Unexpected refresh error",
                )
            else:
                async_delete_missing_show_issue(
                    self.hass, self._entry_id, show.tvmaze_id
                )
                if previous.has_successful_value:
                    change_type = _schedule_change_type(
                        previous.episode, schedule.next_episode
                    )
                    if change_type is not None:
                        self.hass.bus.async_fire(
                            EVENT_SCHEDULE_CHANGED,
                            _schedule_event_data(
                                show,
                                change_type,
                                previous.episode,
                                schedule.next_episode,
                            ),
                        )
                self._states[show.tvmaze_id] = LastKnownState(
                    has_successful_value=True,
                    episode=schedule.next_episode,
                    last_successful_update=attempt,
                    last_update_attempt=attempt,
                    last_attempt_successful=True,
                    show_status=schedule.show_status,
                    previous_episode=schedule.previous_episode,
                    show_image_url=schedule.show_image_url,
                    consecutive_not_found=0,
                    ended_date=schedule.ended_date,
                    network_name=schedule.network_name,
                    web_channel_name=schedule.web_channel_name,
                    schedule_days=schedule.schedule_days,
                    schedule_time=schedule.schedule_time,
                )

    async def _async_save(self) -> None:
        """Atomically save all current states through Home Assistant's Store."""
        try:
            await self._store.async_save(
                {
                    "shows": {
                        str(key): value.as_dict() for key, value in self._states.items()
                    }
                }
            )
        except Exception as err:  # Storage backends can raise implementation errors.
            _LOGGER.error("Unable to persist TV Show Monitor state: %s", err)


def _should_skip_ended_refresh(state: LastKnownState, now: datetime) -> bool:
    """Poll ended shows without upcoming episodes only once every 30 days."""
    if state.show_status != "Ended" or state.episode is not None:
        return False
    if state.last_successful_update is None:
        return False
    try:
        last_success = datetime.fromisoformat(state.last_successful_update)
    except ValueError:
        return False
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=UTC)
    return now - last_success < timedelta(days=ENDED_RECHECK_DAYS)


def _schedule_change_type(
    old: EpisodeInfo | None, new: EpisodeInfo | None
) -> str | None:
    if old is None and new is None:
        return None
    if old is None:
        return "scheduled"
    if new is None:
        return "schedule_cleared"
    if old.episode_id != new.episode_id:
        return "next_episode_changed"
    if old.air_date != new.air_date or old.air_stamp != new.air_stamp:
        return "rescheduled"
    return None


def _schedule_event_data(
    show: ConfiguredShow,
    change_type: str,
    old: EpisodeInfo | None,
    new: EpisodeInfo | None,
) -> dict[str, object]:
    return {
        "tvmaze_show_id": show.tvmaze_id,
        "show_name": show.canonical_name,
        "change_type": change_type,
        "old_episode_id": old.episode_id if old else None,
        "new_episode_id": new.episode_id if new else None,
        "old_air_date": old.air_date if old else None,
        "new_air_date": new.air_date if new else None,
        "old_air_stamp": old.air_stamp if old else None,
        "new_air_stamp": new.air_stamp if new else None,
    }


def _safe_error(err: Exception) -> str:
    """Create a concise, user-safe diagnostic string."""
    message = str(err).strip() or type(err).__name__
    return message[:160]
