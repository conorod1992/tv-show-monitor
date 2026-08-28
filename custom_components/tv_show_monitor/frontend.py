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
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the viewer once per Home Assistant process."""
    if hass.data.get(_FRONTEND_REGISTERED):
        return

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

    if not frontend.async_panel_exists(hass, PANEL_URL_PATH):
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

    hass.data[_FRONTEND_REGISTERED] = True
