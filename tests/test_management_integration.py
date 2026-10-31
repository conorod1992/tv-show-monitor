"""Full Home Assistant setup, WebSocket mutation and registry lifecycle checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_show_monitor.api import ShowSearchCandidate
from custom_components.tv_show_monitor.const import (
    CONF_POLL_INTERVAL,
    CONF_SHOWS,
    DOMAIN,
    ShowScheduleInfo,
)
from custom_components.tv_show_monitor.websocket_api import (
    WS_ADD,
    WS_REMOVE,
)


def _candidate(show_id: int, title: str) -> ShowSearchCandidate:
    return ShowSearchCandidate(
        tvmaze_id=show_id,
        name=title,
        url=f"https://tvmaze.test/{show_id}",
        premiered="2022-01-01",
        status="Running",
        network="Test Network",
        country="United States",
    )


def _entity_ids(hass, entry):
    registry = er.async_get(hass)
    return {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.platform == DOMAIN
    }


def _device_ids(hass, entry):
    return {
        device.id
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
    }


async def test_websocket_add_remove_runs_real_ha_reload_and_registry_cleanup(
    hass, hass_ws_client, severance
):
    """Add and remove a show through actual config-entry reloads and platforms."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
        entry_id="tv-show-monitor-lifecycle",
    )
    entry.add_to_hass(hass)
    # Register frontend HTTP routes before the WebSocket test client freezes
    # the aiohttp router, just as happens during normal Home Assistant boot.
    assert await async_setup_component(hass, "frontend", {})
    client = await hass_ws_client(hass)
    schedule_client = AsyncMock()
    schedule_client.async_get_show_schedule.return_value = ShowScheduleInfo(
        "Running", None, None
    )

    with (
        patch(
            "custom_components.tv_show_monitor.RateLimitedTVMazeClient",
            return_value=schedule_client,
        ),
        patch(
            "custom_components.tv_show_monitor.async_register_frontend",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.tv_show_monitor.async_unregister_frontend",
        ),
        patch(
            "custom_components.tv_show_monitor.websocket_api.TVMazeClient"
        ) as search_client,
    ):
        search_client.return_value.async_search_shows = AsyncMock(
            return_value=[_candidate(2, "Doctor Who")]
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        initial_entities = _entity_ids(hass, entry)
        assert set(initial_entities) == {f"{DOMAIN}_216_next_episode"}
        assert (
            hass.states.get(initial_entities[f"{DOMAIN}_216_next_episode"]) is not None
        )
        assert len(_device_ids(hass, entry)) == 1

        await client.send_json_auto_id(
            {"type": WS_ADD, "query": "Doctor Who", "tvmaze_id": 2}
        )
        added = await client.receive_json()
        assert added["success"], added
        assert added["result"]["reloaded"] is True
        await hass.async_block_till_done()

        after_add = _entity_ids(hass, entry)
        assert set(after_add) == {
            f"{DOMAIN}_216_next_episode",
            f"{DOMAIN}_2_next_episode",
        }
        assert len(_device_ids(hass, entry)) == 2
        assert hass.states.get(after_add[f"{DOMAIN}_2_next_episode"]) is not None
        assert (
            after_add[f"{DOMAIN}_216_next_episode"]
            == initial_entities[f"{DOMAIN}_216_next_episode"]
        )

        await client.send_json_auto_id({"type": WS_REMOVE, "tvmaze_id": 216})
        removed = await client.receive_json()
        assert removed["success"], removed
        assert removed["result"]["reloaded"] is True
        await hass.async_block_till_done()

        after_remove = _entity_ids(hass, entry)
        assert set(after_remove) == {f"{DOMAIN}_2_next_episode"}
        assert hass.states.get(initial_entities[f"{DOMAIN}_216_next_episode"]) is None
        assert len(_device_ids(hass, entry)) == 1
        assert hass.states.get(after_remove[f"{DOMAIN}_2_next_episode"]) is not None

        await client.send_json_auto_id({"type": WS_REMOVE, "tvmaze_id": 2})
        final = await client.receive_json()
        assert final["success"], final
        assert final["result"]["reloaded"] is True
        await hass.async_block_till_done()

        assert _entity_ids(hass, entry) == {}
        assert _device_ids(hass, entry) == set()
        assert hass.states.get(after_remove[f"{DOMAIN}_2_next_episode"]) is None

        assert await hass.config_entries.async_unload(entry.entry_id)
