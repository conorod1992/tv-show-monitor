"""Tests for the config and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tv_show_monitor.const import (
    CONF_POLL_INTERVAL,
    CONF_SHOW_NAMES,
    CONF_SHOWS,
    DOMAIN,
    MAX_SHOWS,
    ConfiguredShow,
)


def resolved(*shows):
    return (list(shows), None, None)


async def test_successful_setup_one_show(hass, severance):
    with patch(
        "custom_components.tv_show_monitor.config_flow._async_resolve_names",
        AsyncMock(return_value=resolved(severance)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "Severance"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SHOWS][0]["tvmaze_id"] == 216


async def test_successful_setup_multiple_blank_and_duplicate_names(hass, severance):
    other = ConfiguredShow(2, "Doctor Who", "Doctor Who")
    resolve = AsyncMock(return_value=resolved(severance, other))
    with patch(
        "custom_components.tv_show_monitor.config_flow._async_resolve_names", resolve
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: " Severance\n\nseverance\nDoctor Who "},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert resolve.call_args.args[1] == ["Severance", "Doctor Who"]


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


@pytest.mark.parametrize("error", ["show_not_found", "duplicate_resolved_show"])
async def test_resolution_errors_do_not_create_partial_entry(hass, error):
    with patch(
        "custom_components.tv_show_monitor.config_flow._async_resolve_names",
        AsyncMock(return_value=([], error, "Bad title")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "Good\nBad title"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == error
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_already_configured(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_SHOWS: [severance.as_dict()]}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.tv_show_monitor.config_flow._async_resolve_names",
        AsyncMock(return_value=resolved(severance)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={CONF_SHOW_NAMES: "Severance"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_list_editing(hass, severance):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SHOWS: [severance.as_dict()]},
        options={CONF_SHOWS: [severance.as_dict()], CONF_POLL_INTERVAL: 24},
    )
    entry.add_to_hass(hass)
    other = ConfiguredShow(2, "Doctor Who", "Doctor Who")
    with (
        patch(
            "custom_components.tv_show_monitor.config_flow._async_resolve_names",
            AsyncMock(return_value=resolved(other)),
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.options.async_init(
            entry.entry_id,
            data={CONF_SHOW_NAMES: "Doctor Who", CONF_POLL_INTERVAL: 48},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_POLL_INTERVAL] == 48
    assert result["data"][CONF_SHOWS][0]["tvmaze_id"] == 2


@pytest.mark.parametrize("interval", [1, 25, 745])
async def test_options_polling_interval_validation(hass, severance, interval):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_SHOWS: [severance.as_dict()]})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(
        entry.entry_id,
        data={CONF_SHOW_NAMES: "Severance", CONF_POLL_INTERVAL: interval},
    )
    assert result["type"] is FlowResultType.FORM
