"""Tests for TV Show Monitor frontend registration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.tv_show_monitor.frontend import (
    PANEL_URL_PATH,
    async_register_frontend,
)


async def test_frontend_panel_starts_hidden_from_sidebar(hass):
    http = MagicMock()
    http.async_register_static_paths = AsyncMock()
    with (
        patch.object(hass, "http", http),
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

    http.async_register_static_paths.assert_awaited_once()
    register.assert_called_once()
    kwargs = register.call_args.kwargs
    assert kwargs["frontend_url_path"] == PANEL_URL_PATH
    assert kwargs["sidebar_default_visible"] is False
    assert kwargs["show_in_sidebar"] is True
    assert kwargs["require_admin"] is False


def test_viewer_exposes_clear_timing_sections() -> None:
    panel = (
        Path(__file__).parents[1]
        / "custom_components"
        / "tv_show_monitor"
        / "frontend"
        / "tv-show-monitor-panel.js"
    ).read_text(encoding="utf-8")

    assert 'this._section("Today", today)' in panel
    assert 'this._section("Coming up", upcoming)' in panel
    assert 'this._section("Recent", recent)' in panel
    assert "<strong>Tomorrow</strong>" in panel
    assert "this._hass?.config?.time_zone" in panel
    assert 'hasEpisode ? this._friendlyAiring(airing, attr) : ""' in panel
