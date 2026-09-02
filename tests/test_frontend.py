"""Tests for TV Show Monitor frontend registration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.tv_show_monitor.frontend import (
    PANEL_URL_PATH,
    async_register_frontend,
    async_unregister_frontend,
)


async def test_frontend_panel_starts_hidden_and_can_be_reregistered(hass):
    http = MagicMock()
    http.async_register_static_paths = AsyncMock()
    panel_state = {"exists": False}

    def panel_exists(*_args):
        return panel_state["exists"]

    def register_panel(*_args, **_kwargs):
        panel_state["exists"] = True

    def remove_panel(*_args, **_kwargs):
        panel_state["exists"] = False

    with (
        patch.object(hass, "http", http),
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_panel_exists",
            side_effect=panel_exists,
        ),
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_register_built_in_panel",
            side_effect=register_panel,
        ) as register,
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_remove_panel",
            side_effect=remove_panel,
        ) as remove,
    ):
        await async_register_frontend(hass)
        await async_register_frontend(hass)
        async_unregister_frontend(hass)
        await async_register_frontend(hass)

    http.async_register_static_paths.assert_awaited_once()
    assert register.call_count == 2
    remove.assert_called_once_with(hass, PANEL_URL_PATH, warn_if_unknown=False)
    kwargs = register.call_args.kwargs
    assert kwargs["frontend_url_path"] == PANEL_URL_PATH
    assert kwargs["sidebar_default_visible"] is False
    assert kwargs["show_in_sidebar"] is True
    assert kwargs["require_admin"] is False


async def test_frontend_does_not_remove_panel_it_did_not_register(hass):
    http = MagicMock()
    http.async_register_static_paths = AsyncMock()
    with (
        patch.object(hass, "http", http),
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_panel_exists",
            return_value=True,
        ),
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_register_built_in_panel"
        ) as register,
        patch(
            "custom_components.tv_show_monitor.frontend.frontend.async_remove_panel"
        ) as remove,
    ):
        await async_register_frontend(hass)
        async_unregister_frontend(hass)

    http.async_register_static_paths.assert_awaited_once()
    register.assert_not_called()
    remove.assert_not_called()


def _panel_source() -> str:
    return (
        Path(__file__).parents[1]
        / "custom_components"
        / "tv_show_monitor"
        / "frontend"
        / "tv-show-monitor-panel.js"
    ).read_text(encoding="utf-8")


def test_viewer_exposes_clear_timing_sections() -> None:
    panel = _panel_source()

    assert 'this._section("Today", today)' in panel
    assert 'this._section("Coming up", upcoming)' in panel
    assert 'this._section("Recent", recent)' in panel
    assert "<strong>Tomorrow</strong>" in panel
    assert "this._hass?.config?.time_zone" in panel
    assert 'hasEpisode ? this._friendlyAiring(airing, whenAttr) : ""' in panel


def test_recent_section_uses_previous_episode_data() -> None:
    panel = _panel_source()

    assert ".map((show) => this._recentFromShow(show))" in panel
    assert "attr.previous_air_stamp" in panel
    assert "attr.previous_episode_code" in panel
    assert "attr.previous_episode_name" in panel
    assert "dayDifference !== 0 && dayDifference !== -1" in panel


def test_viewer_only_selects_integration_owned_entities() -> None:
    panel = _panel_source()

    assert "state.attributes?.tv_show_monitor_entity === true" in panel
    assert "state.attributes?.tvmaze_show_id !== undefined" not in panel


def test_viewer_cards_support_keyboard_activation() -> None:
    panel = _panel_source()

    assert 'element.addEventListener("keydown"' in panel
    assert 'event.key !== "Enter" && event.key !== " "' in panel
    assert "event.preventDefault();" in panel
    assert "openDetails();" in panel


def test_viewer_management_is_admin_only_and_uses_websocket_api() -> None:
    panel = _panel_source()

    assert 'id="manage-shows"' in panel
    assert "this._hass?.user?.is_admin === true" in panel
    assert "type: `${DOMAIN}/config`" in panel
    assert "type: `${DOMAIN}/search`" in panel
    assert "type: `${DOMAIN}/add`" in panel
    assert "type: `${DOMAIN}/remove`" in panel


def test_management_dialog_survives_normal_state_rerenders() -> None:
    panel = _panel_source()

    assert "if (!this._initialized) this._renderShell();" in panel
    assert 'const content = this.shadowRoot.querySelector("#content")' in panel
    assert 'const host = this.shadowRoot.querySelector("#dialog-host")' in panel
    assert "this.shadowRoot.innerHTML" in panel
    assert "content.innerHTML" in panel
