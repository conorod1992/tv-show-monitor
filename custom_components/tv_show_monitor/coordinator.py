"""Coordinator with per-show failure isolation and persistent last-good state."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import TVMazeClient, TVMazeError, TVMazeNotFoundError
from .const import (
    DOMAIN,
    ENDED_RECHECK_DAYS,
    EVENT_EPISODE_AIRING,
    EVENT_EPISODE_TODAY,
    EVENT_SCHEDULE_CHANGED,
    EVENT_STATUS_CHANGED,
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
        self._cancel_day_listener: Callable[[], None] | None = None
        self._airing_listeners: dict[int, Callable[[], None]] = {}

    async def _async_setup(self) -> None:
        """Restore valid state and prune deliberately removed shows."""
        try:
            stored = await self._store.async_load() or {}
        except Exception as err:  # Storage backends can raise implementation errors.
            _LOGGER.error("Unable to load TV Show Monitor persistent state: %s", err)
            self._ensure_day_listener()
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
        self._ensure_day_listener()
        for show in self.shows:
            self._schedule_airing_event(show)
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
                        previous.episode, schedule.next_episode, now
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
                    if (
                        previous.show_status is not None
                        and schedule.show_status is not None
                        and previous.show_status != schedule.show_status
                    ):
                        self.hass.bus.async_fire(
                            EVENT_STATUS_CHANGED,
                            {
                                "tvmaze_show_id": show.tvmaze_id,
                                "show_name": show.canonical_name,
                                "old_status": previous.show_status,
                                "new_status": schedule.show_status,
                            },
                        )

                today_key = _episode_today_key(
                    schedule.next_episode, self.hass.config.time_zone
                )
                airing_key = _episode_airing_key(schedule.next_episode)
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
                    episode_today_fired_key=(
                        previous.episode_today_fired_key
                        if previous.episode_today_fired_key == today_key
                        else None
                    ),
                    episode_airing_fired_key=(
                        previous.episode_airing_fired_key
                        if previous.episode_airing_fired_key == airing_key
                        else None
                    ),
                )
                self._fire_episode_today_if_due(show)
                self._schedule_airing_event(show)

    def _ensure_day_listener(self) -> None:
        """Check for episode-day transitions at local midnight."""
        if self._cancel_day_listener is not None:
            return
        self._cancel_day_listener = async_track_time_change(
            self.hass,
            self._handle_local_midnight,
            hour=0,
            minute=0,
            second=0,
        )

    @callback
    def _handle_local_midnight(self, _now: datetime) -> None:
        """Fire today's episode events once the local date changes."""
        changed = False
        for show in self.shows:
            changed = self._fire_episode_today_if_due(show) or changed
        if changed:
            self.hass.async_create_task(self._async_save())

    def _fire_episode_today_if_due(self, show: ConfiguredShow) -> bool:
        """Fire once when a scheduled episode airs today in Home Assistant time."""
        state = self._states.get(show.tvmaze_id)
        if state is None or state.episode is None:
            return False
        episode = state.episode
        key = _episode_today_key(episode, self.hass.config.time_zone)
        if key is None or state.episode_today_fired_key == key:
            return False
        if (
            _episode_local_air_date(episode, self.hass.config.time_zone)
            != dt_util.now().date().isoformat()
        ):
            return False
        self.hass.bus.async_fire(
            EVENT_EPISODE_TODAY,
            _episode_event_data(show, state, episode),
        )
        self._states[show.tvmaze_id] = replace(state, episode_today_fired_key=key)
        return True

    def _schedule_airing_event(self, show: ConfiguredShow) -> None:
        """Schedule one exact callback for the show's next episode airing."""
        if cancel := self._airing_listeners.pop(show.tvmaze_id, None):
            cancel()
        state = self._states.get(show.tvmaze_id)
        if state is None or state.episode is None:
            return
        episode = state.episode
        key = _episode_airing_key(episode)
        if key is None or state.episode_airing_fired_key == key:
            return
        airing = _episode_airing_datetime(episode, self.hass.config.time_zone)
        if airing is None or airing <= datetime.now(UTC):
            return

        @callback
        def _handle_airing(_now: datetime) -> None:
            self._airing_listeners.pop(show.tvmaze_id, None)
            self.hass.async_create_task(self._async_fire_episode_airing(show, key))

        self._airing_listeners[show.tvmaze_id] = async_track_point_in_time(
            self.hass, _handle_airing, airing
        )

    async def _async_fire_episode_airing(self, show: ConfiguredShow, key: str) -> None:
        """Fire an airing event if the scheduled episode is still current."""
        state = self._states.get(show.tvmaze_id)
        if state is None or state.episode is None:
            return
        if _episode_airing_key(state.episode) != key:
            return
        if state.episode_airing_fired_key == key:
            return
        self.hass.bus.async_fire(
            EVENT_EPISODE_AIRING,
            _episode_event_data(show, state, state.episode),
        )
        self._states[show.tvmaze_id] = replace(state, episode_airing_fired_key=key)
        await self._async_save()

    async def async_shutdown(self) -> None:
        """Cancel integration-owned time listeners."""
        if self._cancel_day_listener is not None:
            self._cancel_day_listener()
            self._cancel_day_listener = None
        for cancel in self._airing_listeners.values():
            cancel()
        self._airing_listeners.clear()
        await super().async_shutdown()

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
    old: EpisodeInfo | None, new: EpisodeInfo | None, now: datetime
) -> str | None:
    if old is None and new is None:
        return None
    if old is None:
        return "scheduled"
    if new is None:
        if _episode_has_aired(old, now):
            return None
        return "schedule_cleared"
    if old.episode_id != new.episode_id:
        if _is_routine_episode_progression(old, new, now):
            return None
        return "next_episode_changed"
    if old.air_date != new.air_date or old.air_stamp != new.air_stamp:
        return "rescheduled"
    return None


def _episode_has_aired(episode: EpisodeInfo, now: datetime) -> bool:
    """Return true when the known episode is safely in the past."""
    airing = _episode_airing_datetime(episode, "UTC")
    if airing is not None and episode.air_stamp is not None:
        return airing <= now
    try:
        air_date = date.fromisoformat(episode.air_date)
    except ValueError:
        return False
    return air_date < now.date()


def _is_routine_episode_progression(
    old: EpisodeInfo, new: EpisodeInfo, now: datetime
) -> bool:
    """Return true when the old next episode has aired and the schedule advanced."""
    if not _episode_has_aired(old, now):
        return False

    if old.season is not None and old.number is not None:
        if new.season is None or new.number is None:
            return False
        return (new.season, new.number) > (old.season, old.number)

    old_sort = old.air_stamp or old.air_date
    new_sort = new.air_stamp or new.air_date
    return new_sort > old_sort


def _episode_today_key(episode: EpisodeInfo | None, local_time_zone: str) -> str | None:
    if episode is None:
        return None
    return f"{episode.episode_id}:{_episode_local_air_date(episode, local_time_zone)}"


def _episode_local_air_date(episode: EpisodeInfo, local_time_zone: str) -> str:
    airing = _episode_airing_datetime(episode, local_time_zone)
    if airing is None:
        return episode.air_date
    try:
        zone = ZoneInfo(local_time_zone)
    except KeyError:
        return episode.air_date
    return airing.astimezone(zone).date().isoformat()


def _episode_airing_key(episode: EpisodeInfo | None) -> str | None:
    if episode is None:
        return None
    stamp = episode.air_stamp or f"{episode.air_date}T{episode.air_time or ''}"
    return f"{episode.episode_id}:{stamp}"


def _episode_airing_datetime(
    episode: EpisodeInfo, local_time_zone: str
) -> datetime | None:
    if episode.air_stamp:
        try:
            airing = datetime.fromisoformat(episode.air_stamp)
        except ValueError:
            return None
        if airing.tzinfo is None:
            airing = airing.replace(tzinfo=UTC)
        return airing.astimezone(UTC)
    if not episode.air_time:
        return None
    try:
        air_date = date.fromisoformat(episode.air_date)
        air_time = time.fromisoformat(episode.air_time)
        zone = ZoneInfo(local_time_zone)
    except ValueError, KeyError:
        return None
    return datetime.combine(air_date, air_time, tzinfo=zone).astimezone(UTC)


def _episode_event_data(
    show: ConfiguredShow, state: LastKnownState, episode: EpisodeInfo
) -> dict[str, object]:
    return {
        "tvmaze_show_id": show.tvmaze_id,
        "show_name": show.canonical_name,
        "episode_id": episode.episode_id,
        "episode_name": episode.name,
        "season": episode.season,
        "episode_number": episode.number,
        "episode_code": _episode_code(episode),
        "air_date": episode.air_date,
        "air_time": episode.air_time,
        "air_stamp": episode.air_stamp,
        "runtime": episode.runtime,
        "network": state.network_name,
        "web_channel": state.web_channel_name,
    }


def _episode_code(episode: EpisodeInfo) -> str | None:
    if episode.season is None or episode.number is None:
        return None
    return f"S{episode.season:02d}E{episode.number:02d}"


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
