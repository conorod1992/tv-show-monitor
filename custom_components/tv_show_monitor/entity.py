"""Base entity for TV Show Monitor."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ConfiguredShow, ShowUpdateResult
from .coordinator import TVShowMonitorCoordinator


class TVShowMonitorEntity(CoordinatorEntity[TVShowMonitorCoordinator]):
    """Common coordinator-backed show entity."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TVShowMonitorCoordinator, show: ConfiguredShow
    ) -> None:
        super().__init__(coordinator)
        self.show = show
        self._attr_unique_id = f"{DOMAIN}_{show.tvmaze_id}_next_episode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(show.tvmaze_id))},
            "name": show.canonical_name,
            "manufacturer": "TVmaze",
            "model": "TV Show",
            "configuration_url": show.show_url,
        }

    @property
    def result(self) -> ShowUpdateResult:
        """Return this show's latest result."""
        return self.coordinator.data[self.show.tvmaze_id]

    async def async_update(self) -> None:
        """Route manual entity updates through the deduplicating coordinator."""
        await self.coordinator.async_request_refresh()
