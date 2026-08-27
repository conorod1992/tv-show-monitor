"""Tests for the config and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_show_monitor.api import ShowSearchCandidate, TVMazeClient, TVMazeError
from custom_components.tv_show_monitor.config_flow import (
    CONF_CANDIDATE_ID,
    CONF_SHOW_ID,
    CONF_SHOW_NAME,
)
from custom_components.tv_show_monitor.const import (
    CONF_POLL_INTERVAL,
    CONF_SHOW_NAMES,
    CONF_SHOWS,
    DOMAIN,
    MAX_SHOWS,
    ConfiguredShow,
)


def candidate(
    tvmaze_id: int,
    name: str,
    *,
    premiered: str | None = "2022-01-01",
    country: str | None = "United States",
) -> ShowSearchCandidate:
    return ShowSearchCandidate(
        tvmaze_id=tvmaze_id,
        name=name,
        url=f"https://tvmaze.test/{tvmaze_id}",
        premiered=premiered,
        status="Running",
        network="Test Network",
        country=country,
    )


async def test_successful_setup_with_clear_exact_match(hass):
    search = AsyncMock(
        return_value=[candidate(216, "Severance"), candidate(999, "Severance Extra")]
    )
    with patch.object(TVMazeClient, "async_search_shows", search):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "Severance"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHOWS][0]["tvmaze_id"] == 216
    search.assert_awaited_once_with("Severance")


async def test_ambiguous_setup_asks_user_to_choose(hass):
    search = AsyncMock(
        return_value=[
            candidate(526, "The Office", premiered="2005-03-24"),
            candidate(2993, "The Office", premiered="2001-07-09", country="UK"),
        ]
    )
    with patch.object(TVMazeClient, "async_search_shows", search):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "The Office"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "select_show"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CANDIDATE_ID: "2993"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHOWS][0]["tvmaze_id"] == 2993


async def test_setup_multiple_titles_only_prompts_for_ambiguous_one(hass):
    search = AsyncMock(
        side_effect=[
            [candidate(216, "Severance")],
            [candidate(526, "The Office"), candidate(2993, "The Office")],
        ]
    )
    with patch.object(TVMazeClient, "async_search_shows", search):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "Severance\nThe Office"},
        )
        assert result["step_id"] == "select_show"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CANDIDATE_ID: "526"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [show["tvmaze_id"] for show in result["data"][CONF_SHOWS]] == [216, 526]


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("\n", "no_shows"),
        ("\n".join(str(i) for i in range(MAX_SHOWS + 1)), "too_many_shows"),
    ],
)
async def test_show_list_validation(hass, raw, error):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_SHOW_NAMES: raw},
    )
    assert result["errors"]["base"] == error


async def test_setup_search_failure_does_not_create_partial_entry(hass):
    with patch.object(
        TVMazeClient, "async_search_shows", AsyncMock(side_effect=TVMazeError("offline"))
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "Severance"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_already_configured(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_SHOWS: [severance.as_dict()]}
    )
    entry.add_to_hass(hass)
    with patch.object(
        TVMazeClient,
        "async_search_shows",
        AsyncMock(return_value=[candidate(216, "Severance")]),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "Severance"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_start_with_management_menu(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == [
        "add_show",
        "remove_show",
        "change_match",
        "poll_interval",
    ]


async def test_add_show_with_ambiguous_results(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    search = AsyncMock(
        return_value=[candidate(526, "The Office"), candidate(2993, "The Office")]
    )
    with (
        patch.object(TVMazeClient, "async_search_shows", search),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "add_show"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHOW_NAME: "The Office"}
        )
        assert result["step_id"] == "add_select"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_CANDIDATE_ID: "526"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [show["tvmaze_id"] for show in result["data"][CONF_SHOWS]] == [216, 526]
    assert result["data"][CONF_POLL_INTERVAL] == 24


async def test_remove_show_does_not_search_tvmaze(hass, severance):
    other = ConfiguredShow(2, "Doctor Who", "Doctor Who")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={
            CONF_SHOWS: [severance.as_dict(), other.as_dict()],
            CONF_POLL_INTERVAL: 48,
        },
    )
    entry.add_to_hass(hass)
    search = AsyncMock(side_effect=TVMazeError("offline"))
    with (
        patch.object(TVMazeClient, "async_search_shows", search),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "remove_show"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHOW_ID: "2"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHOWS] == [severance.as_dict()]
    assert result["data"][CONF_POLL_INTERVAL] == 48
    search.assert_not_awaited()


async def test_cannot_remove_last_show(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_show"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_remove_last_show"


async def test_change_match_replaces_only_selected_show(hass, severance):
    other = ConfiguredShow(2, "Doctor Who", "Doctor Who")
    replacement = candidate(777, "Severance: Alternate")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={
            CONF_SHOWS: [severance.as_dict(), other.as_dict()],
            CONF_POLL_INTERVAL: 24,
        },
    )
    entry.add_to_hass(hass)
    search = AsyncMock(return_value=[replacement])
    with (
        patch.object(TVMazeClient, "async_search_shows", search),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "change_match"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHOW_ID: "216"}
        )
        assert result["step_id"] == "change_match_search"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHOW_NAME: "Severance alternate"}
        )
        assert result["step_id"] == "change_match_select"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_CANDIDATE_ID: "777"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [show["tvmaze_id"] for show in result["data"][CONF_SHOWS]] == [777, 2]
    assert result["data"][CONF_SHOWS][1] == other.as_dict()


async def test_poll_interval_change_never_searches_tvmaze(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    search = AsyncMock(side_effect=TVMazeError("offline"))
    with (
        patch.object(TVMazeClient, "async_search_shows", search),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "poll_interval"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POLL_INTERVAL: 48}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_POLL_INTERVAL] == 48
    assert result["data"][CONF_SHOWS] == [severance.as_dict()]
    search.assert_not_awaited()


@pytest.mark.parametrize("interval", [1, 25, 745])
async def test_poll_interval_validation(hass, severance, interval):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "poll_interval"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: interval}
    )
    assert result["type"] is FlowResultType.FORM
