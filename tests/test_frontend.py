"""Tests for TV Show Monitor frontend registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.tv_show_monitor.frontend import (
    PANEL_URL_PATH,
    async_register_frontend,
)


async def test_frontend_panel_starts_hidden_from_sidebar(hass):
    with (
        patch.object(
            hass.http, "async_register_static_paths", new=AsyncMock()
        ) as static,
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_panel_exists",
            return_value=False,
        ),
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_register_built_in_panel"
        ) as register,
    ):
        await async_register_frontend(hass)
        await async_register_frontend(hass)

    static.assert_awaited_once()
    register.assert_called_once()
    kwargs = register.call_args.kwargs
    assert kwargs["frontend_url_path"] == PANEL_URL_PATH
    assert kwargs["sidebar_default_visible"] is False
    assert kwargs["show_in_sidebar"] is True
    assert kwargs["require_admin"] is False
