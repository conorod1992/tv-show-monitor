"""TV Show Monitor integration setup."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    CONF_POLL_INTERVAL,
    CONF_SHOWS,
    DEFAULT_POLL_INTERVAL_HOURS,
    DOMAIN,
    PLATFORMS,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    ConfiguredShow,
)
from .coordinator import TVShowMonitorCoordinator
from .frontend import async_register_frontend, async_unregister_frontend
from .rate_limited_api import RateLimitedTVMazeClient
from .repairs import async_delete_missing_show_issue
from .websocket_api import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TVShowMonitorRuntimeData:
    """Runtime objects for a loaded config entry."""

    coordinator: TVShowMonitorCoordinator


type TVShowMonitorConfigEntry = ConfigEntry[TVShowMonitorRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: TVShowMonitorConfigEntry
) -> bool:
    """Set up TV Show Monitor from a config entry."""
    async_register_websocket_api(hass)
    await async_register_frontend(hass)
    entry.async_on_unload(lambda: async_unregister_frontend(hass))

    raw_shows = entry.options.get(CONF_SHOWS, entry.data[CONF_SHOWS])
    shows = tuple(ConfiguredShow.from_dict(item) for item in raw_shows)
    await _async_remove_obsolete_registry_entries(hass, entry, shows)
    coordinator = TVShowMonitorCoordinator(
        hass,
        RateLimitedTVMazeClient(async_get_clientsession(hass)),
        shows,
        int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_HOURS)),
        entry,
    )
    entry.async_on_unload(coordinator.async_shutdown)
    entry.runtime_data = TVShowMonitorRuntimeData(coordinator)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TVShowMonitorConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: TVShowMonitorConfigEntry
) -> None:
    """Remove persistent state and repair issues owned by a deleted entry."""
    async_unregister_frontend(hass)

    store: Store[dict[str, object]] = Store(
        hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry.entry_id}"
    )
    try:
        await store.async_remove()
    except Exception as err:  # Storage backends can raise implementation errors.
        _LOGGER.warning(
            "Unable to remove TV Show Monitor persistent state for entry %s: %s",
            entry.entry_id,
            err,
        )

    raw_shows = entry.options.get(CONF_SHOWS, entry.data.get(CONF_SHOWS, []))
    if not isinstance(raw_shows, list):
        return
    for item in raw_shows:
        if not isinstance(item, dict):
            continue
        try:
            tvmaze_id = int(item["tvmaze_id"])
        except KeyError, TypeError, ValueError:
            continue
        async_delete_missing_show_issue(hass, entry.entry_id, tvmaze_id)


async def _async_remove_obsolete_registry_entries(
    hass: HomeAssistant,
    entry: TVShowMonitorConfigEntry,
    shows: tuple[ConfiguredShow, ...],
) -> None:
    """Remove entities/devices and repair issues for deliberately deleted shows."""
    active_ids = {str(show.tvmaze_id) for show in shows}
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.platform != DOMAIN:
            continue
        tvmaze_id = entity_entry.unique_id.removeprefix(f"{DOMAIN}_").removesuffix(
            "_next_episode"
        )
        if tvmaze_id not in active_ids:
            device_id = entity_entry.device_id
            entity_registry.async_remove(entity_entry.entity_id)
            try:
                missing_show_id = int(tvmaze_id)
            except ValueError:
                pass
            else:
                async_delete_missing_show_issue(hass, entry.entry_id, missing_show_id)
            if device_id and not er.async_entries_for_device(
                entity_registry, device_id, include_disabled_entities=True
            ):
                device_registry.async_remove_device(device_id)
