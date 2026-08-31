"""Regression tests for persistent-state write protection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.tv_show_monitor.const import ShowScheduleInfo
from custom_components.tv_show_monitor.coordinator import TVShowMonitorCoordinator


async def test_storage_load_failure_blocks_first_refresh_write(
    hass, severance, episode
):
    """Do not overwrite a cache that could not be loaded during startup."""
    client = AsyncMock()
    client.async_get_show_schedule.return_value = ShowScheduleInfo(
        "Running", episode, None
    )
    entry = MagicMock(entry_id="test")
    coordinator = TVShowMonitorCoordinator(hass, client, (severance,), 24, entry)
    store = AsyncMock()
    store.async_load.side_effect = OSError("read failed")
    coordinator._store = store

    try:
        await coordinator._async_setup()
        data = await coordinator._async_update_data()
        await coordinator._async_save()

        assert data[216].state.episode == episode
        assert coordinator._storage_writes_enabled is False
        store.async_save.assert_not_awaited()
    finally:
        await coordinator.async_shutdown()
