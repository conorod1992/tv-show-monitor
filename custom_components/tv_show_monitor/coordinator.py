"""Coordinator with per-show failure isolation and persistent last-good state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import TVMazeClient, TVMazeError
from .const import (
    DOMAIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    ConfiguredShow,
    LastKnownState,
    ShowUpdateResult,
    utc_now_iso,
)

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
                        self._states[show.tvmaze_id] = LastKnownState.from_dict(raw)
                    except KeyError, TypeError, ValueError:
                        _LOGGER.warning(
                            "Ignoring invalid persisted state for TVmaze show ID %s",
                            show.tvmaze_id,
                        )
        await self._async_save()

    async def _async_update_data(self) -> dict[int, ShowUpdateResult]:
        """Refresh every configured show, preserving last-good state on errors."""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        await asyncio.gather(
            *(self._async_refresh_show(show, semaphore) for show in self.shows)
        )
        await self._async_save()
        return {
            show.tvmaze_id: ShowUpdateResult(
                show, self._states.get(show.tvmaze_id, LastKnownState())
            )
            for show in self.shows
        }

    async def _async_refresh_show(
        self, show: ConfiguredShow, semaphore: asyncio.Semaphore
    ) -> None:
        """Refresh one show while respecting the per-cycle concurrency limit."""
        async with semaphore:
            attempt = utc_now_iso()
            previous = self._states.get(show.tvmaze_id, LastKnownState())
            try:
                episode = await self.client.async_get_next_episode(show.tvmaze_id)
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
                self._states[show.tvmaze_id] = LastKnownState(
                    has_successful_value=True,
                    episode=episode,
                    last_successful_update=attempt,
                    last_update_attempt=attempt,
                    last_attempt_successful=True,
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


def _safe_error(err: Exception) -> str:
    """Create a concise, user-safe diagnostic string."""
    message = str(err).strip() or type(err).__name__
    return message[:160]
