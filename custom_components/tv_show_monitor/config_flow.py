"""UI configuration for TV Show Monitor."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TVMazeClient, TVMazeError
from .const import (
    CONF_POLL_INTERVAL,
    CONF_SHOW_NAMES,
    CONF_SHOWS,
    DEFAULT_POLL_INTERVAL_HOURS,
    DOMAIN,
    MAX_POLL_INTERVAL_HOURS,
    MAX_SHOWS,
    MIN_POLL_INTERVAL_HOURS,
    NAME,
    ConfiguredShow,
)

_LOGGER = logging.getLogger(__name__)


class TVShowMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a singleton TV Show Monitor entry."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> TVShowMonitorOptionsFlow:
        """Return the options flow."""
        return TVShowMonitorOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Resolve and configure one or more shows."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            names, error = _normalise_names(str(user_input[CONF_SHOW_NAMES]))
            if error:
                errors["base"] = error
            else:
                shows, error, failing_title = await _async_resolve_names(
                    self.hass, names
                )
                if error:
                    errors["base"] = error
                    if failing_title:
                        placeholders["title"] = failing_title
                else:
                    await self.async_set_unique_id(DOMAIN)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=NAME,
                        data={CONF_SHOWS: [show.as_dict() for show in shows]},
                        options={
                            CONF_SHOWS: [show.as_dict() for show in shows],
                            CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL_HOURS,
                        },
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=_show_schema(user_input),
            errors=errors,
            description_placeholders=placeholders,
        )


class TVShowMonitorOptionsFlow(OptionsFlowWithReload):
    """Replace the show list and adjust the poll interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            names, error = _normalise_names(str(user_input[CONF_SHOW_NAMES]))
            interval = int(user_input[CONF_POLL_INTERVAL])
            if error:
                errors["base"] = error
            elif interval < MIN_POLL_INTERVAL_HOURS:
                errors[CONF_POLL_INTERVAL] = "poll_interval_too_short"
            elif interval > MAX_POLL_INTERVAL_HOURS:
                errors[CONF_POLL_INTERVAL] = "poll_interval_too_long"
            elif interval % 24:
                errors[CONF_POLL_INTERVAL] = "poll_interval_invalid_step"
            else:
                shows, error, failing_title = await _async_resolve_options_names(
                    self.hass, names, _entry_shows(self.config_entry)
                )
                if error:
                    errors["base"] = error
                    if failing_title:
                        placeholders["title"] = failing_title
                elif _ids_overlap_other_entries(
                    self.hass.config_entries.async_entries(DOMAIN),
                    self.config_entry.entry_id,
                    shows,
                ):
                    errors["base"] = "already_configured_show"
                else:
                    return self.async_create_entry(
                        data={
                            CONF_SHOWS: [show.as_dict() for show in shows],
                            CONF_POLL_INTERVAL: interval,
                        }
                    )

        current = _entry_shows(self.config_entry)
        defaults = {
            CONF_SHOW_NAMES: "\n".join(show.entered_name for show in current),
            CONF_POLL_INTERVAL: self.config_entry.options.get(
                CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_HOURS
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(user_input or defaults),
            errors=errors,
            description_placeholders=placeholders,
        )


def _show_schema(values: dict[str, Any] | None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SHOW_NAMES,
                default=(values or {}).get(CONF_SHOW_NAMES, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=True, type=selector.TextSelectorType.TEXT
                )
            )
        }
    )


def _options_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SHOW_NAMES, default=values.get(CONF_SHOW_NAMES, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=True, type=selector.TextSelectorType.TEXT
                )
            ),
            vol.Required(
                CONF_POLL_INTERVAL,
                default=values.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_HOURS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_POLL_INTERVAL_HOURS,
                    max=MAX_POLL_INTERVAL_HOURS,
                    step=24,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="hours",
                )
            ),
        }
    )


def _normalise_names(raw: str) -> tuple[list[str], str | None]:
    names: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        name = line.strip()
        folded = name.casefold()
        if name and folded not in seen:
            seen.add(folded)
            names.append(name)
    if not names:
        return [], "no_shows"
    if len(names) > MAX_SHOWS:
        return [], "too_many_shows"
    return names, None


async def _async_resolve_names(
    hass: Any, names: list[str]
) -> tuple[list[ConfiguredShow], str | None, str | None]:
    client = TVMazeClient(async_get_clientsession(hass))
    shows: list[ConfiguredShow] = []
    ids: set[int] = set()
    for name in names:
        try:
            show = await client.async_search_show(name)
        except TVMazeError as err:
            _LOGGER.warning("Failed to resolve TV show title %r: %s", name, err)
            return [], "cannot_connect", name
        if show is None:
            _LOGGER.info("TVmaze returned no result for title %r", name)
            return [], "show_not_found", name
        if show.tvmaze_id in ids:
            return [], "duplicate_resolved_show", name
        ids.add(show.tvmaze_id)
        shows.append(show)
    return shows, None, None


async def _async_resolve_options_names(
    hass: Any,
    names: list[str],
    current: tuple[ConfiguredShow, ...],
) -> tuple[list[ConfiguredShow], str | None, str | None]:
    """Resolve only new or renamed options entries and retain stable matches."""
    existing_by_name = {show.entered_name.casefold(): show for show in current}
    client: TVMazeClient | None = None
    shows: list[ConfiguredShow] = []
    ids: set[int] = set()

    for name in names:
        show = existing_by_name.get(name.casefold())
        if show is not None:
            show = replace(show, entered_name=name)
        else:
            if client is None:
                client = TVMazeClient(async_get_clientsession(hass))
            try:
                show = await client.async_search_show(name)
            except TVMazeError as err:
                _LOGGER.warning("Failed to resolve TV show title %r: %s", name, err)
                return [], "cannot_connect", name
            if show is None:
                _LOGGER.info("TVmaze returned no result for title %r", name)
                return [], "show_not_found", name

        if show.tvmaze_id in ids:
            return [], "duplicate_resolved_show", name
        ids.add(show.tvmaze_id)
        shows.append(show)

    return shows, None, None


def _entry_shows(entry: ConfigEntry) -> tuple[ConfiguredShow, ...]:
    raw = entry.options.get(CONF_SHOWS, entry.data.get(CONF_SHOWS, []))
    return tuple(ConfiguredShow.from_dict(item) for item in raw)


def _ids_overlap_other_entries(
    entries: list[ConfigEntry], entry_id: str, shows: list[ConfiguredShow]
) -> bool:
    candidate_ids = {show.tvmaze_id for show in shows}
    for entry in entries:
        if entry.entry_id == entry_id:
            continue
        if candidate_ids & {show.tvmaze_id for show in _entry_shows(entry)}:
            return True
    return False
