"""Repair issues for TV Show Monitor."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ConfiguredShow


def missing_show_issue_id(entry_id: str, tvmaze_id: int) -> str:
    """Return the stable issue ID for a missing TVmaze show."""
    return f"missing_show_{entry_id}_{tvmaze_id}"


@callback
def async_create_missing_show_issue(
    hass: HomeAssistant, entry_id: str, show: ConfiguredShow
) -> None:
    """Create a warning when a configured TVmaze ID repeatedly returns 404."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        missing_show_issue_id(entry_id, show.tvmaze_id),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="show_missing",
        translation_placeholders={
            "show_name": show.canonical_name,
            "tvmaze_id": str(show.tvmaze_id),
        },
    )


@callback
def async_delete_missing_show_issue(
    hass: HomeAssistant, entry_id: str, tvmaze_id: int
) -> None:
    """Clear the warning after recovery or deliberate removal."""
    ir.async_delete_issue(
        hass,
        DOMAIN,
        missing_show_issue_id(entry_id, tvmaze_id),
    )
