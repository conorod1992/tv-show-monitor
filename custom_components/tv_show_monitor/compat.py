"""Bridge Home Assistant's validation and HTTP module migrations."""

# Optional-import and duplicate-alias diagnostics differ between HA versions.
# mypy: warn-unused-ignores=False

from homeassistant.helpers import config_validation as cv

# Select HA's backend, even if both validation libraries happen to be installed.
if hasattr(cv, "probatio"):
    import probatio as vol  # type: ignore[import-not-found]
else:
    import voluptuous as vol  # type: ignore[no-redef]

try:
    import homeassistant.components.http.server as _http
except ImportError:
    import homeassistant.components.http as _http  # type: ignore[no-redef]

StaticPathConfig = _http.StaticPathConfig

__all__ = ["StaticPathConfig", "vol"]
