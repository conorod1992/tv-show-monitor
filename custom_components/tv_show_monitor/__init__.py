"""TV Show Monitor integration setup."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TVMazeClient
from .const import (
    CONF_POLL_INTERVAL,
    CONF_SHOWS,
    DEFAULT_POLL_INTERVAL_HOURS,
    DOMAIN,
    PLATFORMS,
    ConfiguredShow,
)
from .coordinator import TVShowMonitorCoordinator
from .repairs import async_delete_missing_show_issue


@dataclass(slots=True)
class TVShowMonitorRuntimeData:
    """Runtime objects for a loaded config entry."""

    coordinator: TVShowMonitorCoordinator


type TVShowMonitorConfigEntry = ConfigEntry[TVShowMonitorRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: TVShowMonitorConfigEntry
) -> bool:
    """Set up TV Show Monitor from a config entry."""
    raw_shows = entry.options.get(CONF_SHOWS, entry.data[CONF_SHOWS])
    shows = tuple(ConfiguredShow.from_dict(item) for item in raw_shows)
    await _async_remove_obsolete_registry_entries(hass, entry, shows)
    coordinator = TVShowMonitorCoordinator(
        hass,
        TVMazeClient(async_get_clientsession(hass)),
        shows,
        int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_HOURS)),
        entry,
    )
    entry.runtime_data = TVShowMonitorRuntimeData(coordinator)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TVShowMonitorConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


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
