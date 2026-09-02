"""WebSocket API used by the TV Show Monitor viewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShowSearchCandidate, TVMazeClient, TVMazeError
from .const import (
    CONF_POLL_INTERVAL,
    CONF_SHOWS,
    DEFAULT_POLL_INTERVAL_HOURS,
    DOMAIN,
    MAX_SHOWS,
    ConfiguredShow,
)

if TYPE_CHECKING:
    from homeassistant.components.websocket_api import ActiveConnection

_LOGGER = logging.getLogger(__name__)
_REGISTERED = f"{DOMAIN}_websocket_api_registered"
WS_CONFIG = f"{DOMAIN}/config"
WS_SEARCH = f"{DOMAIN}/search"
WS_ADD = f"{DOMAIN}/add"
WS_REMOVE = f"{DOMAIN}/remove"


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register viewer management commands once per Home Assistant process."""
    if hass.data.get(_REGISTERED):
        return

    websocket_api.async_register_command(hass, websocket_config)
    websocket_api.async_register_command(hass, websocket_search)
    websocket_api.async_register_command(hass, websocket_add)
    websocket_api.async_register_command(hass, websocket_remove)
    hass.data[_REGISTERED] = True


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): WS_CONFIG})
def websocket_config(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the authoritative configured-show list for the viewer."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "TV Show Monitor is not configured")
        return
    connection.send_result(msg["id"], _config_payload(entry))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_SEARCH,
        vol.Required("query"): vol.All(str, vol.Length(min=1, max=100)),
    }
)
@websocket_api.async_response
async def websocket_search(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Search TVmaze for shows that can be added from the viewer."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "TV Show Monitor is not configured")
        return

    query = msg["query"].strip()
    if not query:
        connection.send_error(msg["id"], "invalid_query", "Enter a show title")
        return

    client = TVMazeClient(async_get_clientsession(hass))
    try:
        candidates = await client.async_search_shows(query)
    except TVMazeError as err:
        _LOGGER.warning("Viewer TVmaze search failed for %r: %s", query, err)
        connection.send_error(msg["id"], "cannot_connect", "Unable to search TVmaze")
        return

    configured_ids = {show.tvmaze_id for show in _entry_shows(entry)}
    connection.send_result(
        msg["id"],
        {
            "query": query,
            "candidates": [
                _candidate_payload(candidate, candidate.tvmaze_id in configured_ids)
                for candidate in candidates
            ],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_ADD,
        vol.Required("query"): vol.All(str, vol.Length(min=1, max=100)),
        vol.Required("tvmaze_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)
@websocket_api.async_response
async def websocket_add(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Validate and add a selected TVmaze search result."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "TV Show Monitor is not configured")
        return

    current = _entry_shows(entry)
    if len(current) >= MAX_SHOWS:
        connection.send_error(
            msg["id"], "too_many_shows", f"A maximum of {MAX_SHOWS} shows is supported"
        )
        return

    tvmaze_id = msg["tvmaze_id"]
    if tvmaze_id in {show.tvmaze_id for show in current}:
        connection.send_error(msg["id"], "duplicate_show", "That show is already being monitored")
        return

    query = msg["query"].strip()
    if not query:
        connection.send_error(msg["id"], "invalid_query", "Enter a show title")
        return

    client = TVMazeClient(async_get_clientsession(hass))
    try:
        candidates = await client.async_search_shows(query)
    except TVMazeError as err:
        _LOGGER.warning("Viewer TVmaze validation failed for %r: %s", query, err)
        connection.send_error(msg["id"], "cannot_connect", "Unable to verify the TVmaze show")
        return

    candidate = next(
        (candidate for candidate in candidates if candidate.tvmaze_id == tvmaze_id),
        None,
    )
    if candidate is None:
        connection.send_error(
            msg["id"],
            "invalid_selection",
            "The selected show is no longer present in the TVmaze search results",
        )
        return

    shows = (*current, candidate.as_configured_show(query))
    reloaded = await _async_replace_shows(hass, entry, shows)
    connection.send_result(msg["id"], {**_config_payload(entry), "reloaded": reloaded})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_REMOVE,
        vol.Required("tvmaze_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)
@websocket_api.async_response
async def websocket_remove(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a configured show, including the final remaining show."""
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_configured", "TV Show Monitor is not configured")
        return

    current = _entry_shows(entry)
    tvmaze_id = msg["tvmaze_id"]
    if tvmaze_id not in {show.tvmaze_id for show in current}:
        connection.send_error(msg["id"], "unknown_show", "That show is not configured")
        return

    shows = tuple(show for show in current if show.tvmaze_id != tvmaze_id)
    reloaded = await _async_replace_shows(hass, entry, shows)
    connection.send_result(msg["id"], {**_config_payload(entry), "reloaded": reloaded})


def _entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the singleton TV Show Monitor config entry."""
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _entry_shows(entry: ConfigEntry) -> tuple[ConfiguredShow, ...]:
    """Return the configured shows, preferring current options."""
    raw = entry.options.get(CONF_SHOWS, entry.data.get(CONF_SHOWS, []))
    return tuple(ConfiguredShow.from_dict(item) for item in raw)


def _entry_poll_interval(entry: ConfigEntry) -> int:
    """Return the configured polling interval."""
    return int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_HOURS))


async def _async_replace_shows(
    hass: HomeAssistant,
    entry: ConfigEntry,
    shows: tuple[ConfiguredShow, ...],
) -> bool:
    """Persist a replacement show list and reload the entry."""
    options = dict(entry.options)
    options[CONF_SHOWS] = [show.as_dict() for show in shows]
    options[CONF_POLL_INTERVAL] = _entry_poll_interval(entry)
    hass.config_entries.async_update_entry(entry, options=options)
    try:
        return await hass.config_entries.async_reload(entry.entry_id)
    except Exception:  # Home Assistant owns reload failures; keep the saved options.
        _LOGGER.exception("Unable to reload TV Show Monitor after updating followed shows")
        return False


def _config_payload(entry: ConfigEntry) -> dict[str, Any]:
    """Return frontend-safe management configuration."""
    shows = _entry_shows(entry)
    return {
        "shows": [show.as_dict() for show in shows],
        "show_count": len(shows),
        "max_shows": MAX_SHOWS,
    }


def _candidate_payload(
    candidate: ShowSearchCandidate, already_added: bool
) -> dict[str, Any]:
    """Return a frontend-safe TVmaze search result."""
    return {
        "tvmaze_id": candidate.tvmaze_id,
        "name": candidate.name,
        "url": candidate.url,
        "premiered": candidate.premiered,
        "status": candidate.status,
        "network": candidate.network,
        "country": candidate.country,
        "label": candidate.label,
        "already_added": already_added,
    }
