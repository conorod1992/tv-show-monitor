"""Tests for the TV Show Monitor viewer WebSocket API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_show_monitor.api import ShowSearchCandidate, TVMazeClient
from custom_components.tv_show_monitor.const import (
    CONF_POLL_INTERVAL,
    CONF_SHOWS,
    DOMAIN,
)
from custom_components.tv_show_monitor.websocket_api import (
    WS_ADD,
    WS_CONFIG,
    WS_REMOVE,
    WS_SEARCH,
    async_register_websocket_api,
)


def candidate(tvmaze_id: int, name: str) -> ShowSearchCandidate:
    """Return a TVmaze search candidate."""
    return ShowSearchCandidate(
        tvmaze_id=tvmaze_id,
        name=name,
        url=f"https://tvmaze.test/{tvmaze_id}",
        premiered="2022-01-01",
        status="Running",
        network="Test Network",
        country="United States",
    )


async def _management_client(hass, hass_ws_client):
    client = await hass_ws_client(hass)
    async_register_websocket_api(hass)
    return client


async def test_config_returns_authoritative_show_list(hass, hass_ws_client, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    client = await _management_client(hass, hass_ws_client)

    await client.send_json_auto_id({"type": WS_CONFIG})
    response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["shows"] == [severance.as_dict()]
    assert response["result"]["show_count"] == 1
    assert response["result"]["max_shows"] == 50


async def test_search_marks_already_configured_results(
    hass, hass_ws_client, severance
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    client = await _management_client(hass, hass_ws_client)
    search = AsyncMock(
        return_value=[candidate(216, "Severance"), candidate(2, "Doctor Who")]
    )

    with patch.object(TVMazeClient, "async_search_shows", search):
        await client.send_json_auto_id({"type": WS_SEARCH, "query": "Severance"})
        response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["query"] == "Severance"
    assert response["result"]["candidates"][0]["already_added"] is True
    assert response["result"]["candidates"][1]["already_added"] is False
    search.assert_awaited_once_with("Severance")


async def test_add_validates_selection_saves_options_and_reloads(
    hass, hass_ws_client, severance
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 48},
    )
    entry.add_to_hass(hass)
    client = await _management_client(hass, hass_ws_client)
    search = AsyncMock(return_value=[candidate(2, "Doctor Who")])
    reload_entry = AsyncMock(return_value=True)

    with (
        patch.object(TVMazeClient, "async_search_shows", search),
        patch.object(hass.config_entries, "async_reload", reload_entry),
    ):
        await client.send_json_auto_id(
            {"type": WS_ADD, "query": "Doctor Who", "tvmaze_id": 2}
        )
        response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["reloaded"] is True
    assert [show["tvmaze_id"] for show in entry.options[CONF_SHOWS]] == [216, 2]
    assert entry.options[CONF_POLL_INTERVAL] == 48
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_remove_can_leave_an_empty_show_list(hass, hass_ws_client, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    client = await _management_client(hass, hass_ws_client)
    reload_entry = AsyncMock(return_value=True)

    with patch.object(hass.config_entries, "async_reload", reload_entry):
        await client.send_json_auto_id({"type": WS_REMOVE, "tvmaze_id": 216})
        response = await client.receive_json()

    assert response["success"] is True
    assert response["result"]["shows"] == []
    assert entry.options[CONF_SHOWS] == []
    reload_entry.assert_awaited_once_with(entry.entry_id)
