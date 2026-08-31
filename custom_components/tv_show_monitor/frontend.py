"""Frontend panel registration for TV Show Monitor."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, NAME

PANEL_URL_PATH = "tv-show-monitor"
PANEL_COMPONENT_NAME = "tv-show-monitor-panel"
FRONTEND_URL_BASE = "/tv_show_monitor_frontend"
FRONTEND_FILE = "tv-show-monitor-panel.js"
_STATIC_PATH_REGISTERED = f"{DOMAIN}_static_path_registered"
_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register static assets once and ensure the viewer panel exists."""
    if not hass.data.get(_STATIC_PATH_REGISTERED):
        frontend_dir = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    FRONTEND_URL_BASE,
                    str(frontend_dir),
                    cache_headers=False,
                )
            ]
        )
        hass.data[_STATIC_PATH_REGISTERED] = True

    if frontend.async_panel_exists(hass, PANEL_URL_PATH):
        return

    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=NAME,
        sidebar_icon="mdi:television-classic",
        sidebar_default_visible=False,
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": PANEL_COMPONENT_NAME,
                "embed_iframe": False,
                "trust_external": False,
                "module_url": f"{FRONTEND_URL_BASE}/{FRONTEND_FILE}",
            }
        },
        require_admin=False,
        show_in_sidebar=True,
    )
    hass.data[_PANEL_REGISTERED] = True


def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Remove the viewer panel while leaving the process-wide static route intact."""
    if not hass.data.pop(_PANEL_REGISTERED, False):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
