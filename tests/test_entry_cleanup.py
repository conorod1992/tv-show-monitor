"""Regression tests for config-entry lifecycle cleanup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_show_monitor import (
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.tv_show_monitor.const import (
    CONF_SHOWS,
    DOMAIN,
    PLATFORMS,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)


async def test_unload_delegates_to_platforms():
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry = MagicMock()

    assert await async_unload_entry(hass, entry) is True

    hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, PLATFORMS)


async def test_setup_rollback_cleans_frontend_before_show_parsing(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry-123",
        data={CONF_SHOWS: [{}]},
    )

    with (
        patch(
            "custom_components.tv_show_monitor.async_register_frontend",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.tv_show_monitor.async_unregister_frontend"
        ) as unregister,
        pytest.raises(KeyError),
    ):
        await async_setup_entry(hass, entry)

    await entry._async_process_on_unload(hass)
    await hass.async_block_till_done()

    unregister.assert_called_once_with(hass)


async def test_setup_rollback_shuts_down_coordinator(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry-123",
        data={CONF_SHOWS: [severance.as_dict()]},
    )
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=RuntimeError("setup failed")
    )
    coordinator.async_shutdown = AsyncMock()

    with (
        patch(
            "custom_components.tv_show_monitor.async_register_frontend",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.tv_show_monitor.async_unregister_frontend"
        ) as unregister,
        patch(
            "custom_components.tv_show_monitor._async_remove_obsolete_registry_entries",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.tv_show_monitor.TVShowMonitorCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(RuntimeError, match="setup failed"),
    ):
        await async_setup_entry(hass, entry)

    await entry._async_process_on_unload(hass)
    await hass.async_block_till_done()

    coordinator.async_shutdown.assert_awaited_once()
    unregister.assert_called_once_with(hass)


async def test_remove_entry_deletes_store_and_repair_issues(severance):
    hass = MagicMock()
    entry = MagicMock(
        entry_id="entry-123",
        options={CONF_SHOWS: [severance.as_dict()]},
        data={CONF_SHOWS: [severance.as_dict()]},
    )
    store = MagicMock()
    store.async_remove = AsyncMock()

    with (
        patch(
            "custom_components.tv_show_monitor.Store", return_value=store
        ) as store_cls,
        patch(
            "custom_components.tv_show_monitor.async_delete_missing_show_issue"
        ) as delete_issue,
        patch(
            "custom_components.tv_show_monitor.async_unregister_frontend"
        ) as unregister,
    ):
        await async_remove_entry(hass, entry)

    unregister.assert_called_once_with(hass)
    store_cls.assert_called_once_with(
        hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.entry-123"
    )
    store.async_remove.assert_awaited_once()
    delete_issue.assert_called_once_with(hass, "entry-123", severance.tvmaze_id)


async def test_store_cleanup_failure_does_not_block_entry_removal(severance):
    hass = MagicMock()
    entry = MagicMock(
        entry_id="entry-123",
        options={CONF_SHOWS: [severance.as_dict()]},
        data={CONF_SHOWS: [severance.as_dict()]},
    )
    store = MagicMock()
    store.async_remove = AsyncMock(side_effect=OSError("disk unavailable"))

    with (
        patch("custom_components.tv_show_monitor.Store", return_value=store),
        patch(
            "custom_components.tv_show_monitor.async_delete_missing_show_issue"
        ) as delete_issue,
        patch("custom_components.tv_show_monitor.async_unregister_frontend"),
    ):
        await async_remove_entry(hass, entry)

    delete_issue.assert_called_once_with(hass, "entry-123", severance.tvmaze_id)
