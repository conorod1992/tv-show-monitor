"""Regression tests for config-entry lifecycle cleanup."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.tv_show_monitor import async_remove_entry, async_unload_entry
from custom_components.tv_show_monitor.const import (
    CONF_SHOWS,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)


async def test_successful_unload_shuts_down_and_removes_panel():
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock()
    entry = MagicMock(runtime_data=SimpleNamespace(coordinator=coordinator))

    with patch(
        "custom_components.tv_show_monitor.async_unregister_frontend"
    ) as unregister:
        assert await async_unload_entry(hass, entry) is True

    coordinator.async_shutdown.assert_awaited_once()
    unregister.assert_called_once_with(hass)


async def test_failed_unload_keeps_runtime_resources():
    hass = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock()
    entry = MagicMock(runtime_data=SimpleNamespace(coordinator=coordinator))

    with patch(
        "custom_components.tv_show_monitor.async_unregister_frontend"
    ) as unregister:
        assert await async_unload_entry(hass, entry) is False

    coordinator.async_shutdown.assert_not_awaited()
    unregister.assert_not_called()


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
