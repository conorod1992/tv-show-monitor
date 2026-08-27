"""UI configuration for TV Show Monitor."""

from __future__ import annotations

import logging
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

from .api import ShowSearchCandidate, TVMazeClient, TVMazeError
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
CONF_CANDIDATE_ID = "candidate_id"
CONF_SHOW_ID = "show_id"
CONF_SHOW_NAME = "show_name"


class TVShowMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a singleton TV Show Monitor entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._setup_raw = ""
        self._setup_pending: list[str] = []
        self._setup_selected: list[ConfiguredShow] = []
        self._pending_query: str | None = None
        self._pending_candidates: list[ShowSearchCandidate] = []

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> TVShowMonitorOptionsFlow:
        """Return the options flow."""
        return TVShowMonitorOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect show names and resolve them against TVmaze."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            self._setup_raw = str(user_input[CONF_SHOW_NAMES])
            names, error = _normalise_names(self._setup_raw)
            if error:
                errors["base"] = error
            else:
                self._setup_pending = names
                self._setup_selected = []
                return await self._async_continue_setup()
        return self.async_show_form(
            step_id="user",
            data_schema=_show_schema(user_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_select_show(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user disambiguate an ambiguous setup search."""
        if not self._pending_query or not self._pending_candidates:
            return await self.async_step_user()
        if user_input is None:
            return self._candidate_form("select_show", self._pending_candidates)

        candidate = _candidate_by_id(
            self._pending_candidates, int(user_input[CONF_CANDIDATE_ID])
        )
        if candidate is None:
            return self._candidate_form(
                "select_show", self._pending_candidates, {"base": "invalid_selection"}
            )
        if candidate.tvmaze_id in {show.tvmaze_id for show in self._setup_selected}:
            return self.async_show_form(
                step_id="user",
                data_schema=_show_schema({CONF_SHOW_NAMES: self._setup_raw}),
                errors={"base": "duplicate_resolved_show"},
                description_placeholders={"title": self._pending_query},
            )
        self._setup_selected.append(candidate.as_configured_show(self._pending_query))
        self._pending_query = None
        self._pending_candidates = []
        return await self._async_continue_setup()

    async def _async_continue_setup(self) -> ConfigFlowResult:
        while self._setup_pending:
            query = self._setup_pending.pop(0)
            candidates, error = await _async_search_candidates(self.hass, query)
            if error:
                return self.async_show_form(
                    step_id="user",
                    data_schema=_show_schema({CONF_SHOW_NAMES: self._setup_raw}),
                    errors={"base": error},
                    description_placeholders={"title": query},
                )
            candidate = _automatic_candidate(query, candidates)
            if candidate is None:
                self._pending_query = query
                self._pending_candidates = candidates
                return self._candidate_form("select_show", candidates)
            if candidate.tvmaze_id in {show.tvmaze_id for show in self._setup_selected}:
                return self.async_show_form(
                    step_id="user",
                    data_schema=_show_schema({CONF_SHOW_NAMES: self._setup_raw}),
                    errors={"base": "duplicate_resolved_show"},
                    description_placeholders={"title": query},
                )
            self._setup_selected.append(candidate.as_configured_show(query))

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        shows = [show.as_dict() for show in self._setup_selected]
        return self.async_create_entry(
            title=NAME,
            data={CONF_SHOWS: shows},
            options={
                CONF_SHOWS: shows,
                CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL_HOURS,
            },
        )

    def _candidate_form(
        self,
        step_id: str,
        candidates: list[ShowSearchCandidate],
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=_candidate_schema(candidates),
            errors=errors or {},
            description_placeholders={"title": self._pending_query or ""},
        )


class TVShowMonitorOptionsFlow(OptionsFlowWithReload):
    """Manage followed shows and polling without replacing a multiline list."""

    def __init__(self) -> None:
        self._pending_query: str | None = None
        self._pending_candidates: list[ShowSearchCandidate] = []
        self._change_show_id: int | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options management menu."""
        current = _entry_shows(self.config_entry)
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_show", "remove_show", "change_match", "poll_interval"],
            description_placeholders={
                "show_count": str(len(current)),
                "poll_interval": str(_entry_poll_interval(self.config_entry)),
            },
        )

    async def async_step_add_show(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search for and add one show."""
        current = _entry_shows(self.config_entry)
        if len(current) >= MAX_SHOWS:
            return self.async_show_form(
                step_id="add_show",
                data_schema=_single_show_schema(user_input),
                errors={"base": "too_many_shows"},
            )
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            query = str(user_input[CONF_SHOW_NAME]).strip()
            if not query:
                errors["base"] = "no_shows"
            else:
                candidates, error = await _async_search_candidates(self.hass, query)
                if error:
                    errors["base"] = error
                    placeholders["title"] = query
                else:
                    self._pending_query = query
                    self._pending_candidates = candidates
                    candidate = _automatic_candidate(query, candidates)
                    if candidate is not None:
                        return self._finish_add(candidate)
                    return self._candidate_form("add_select")
        return self.async_show_form(
            step_id="add_show",
            data_schema=_single_show_schema(user_input),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_add_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose an ambiguous TVmaze result to add."""
        if not self._pending_query or not self._pending_candidates:
            return await self.async_step_add_show()
        if user_input is None:
            return self._candidate_form("add_select")
        candidate = _candidate_by_id(
            self._pending_candidates, int(user_input[CONF_CANDIDATE_ID])
        )
        if candidate is None:
            return self._candidate_form("add_select", {"base": "invalid_selection"})
        return self._finish_add(candidate)

    async def async_step_remove_show(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one followed show without resolving any titles."""
        current = _entry_shows(self.config_entry)
        if len(current) <= 1:
            return self.async_show_form(
                step_id="remove_show",
                data_schema=_show_choice_schema(current),
                errors={"base": "cannot_remove_last_show"},
            )
        if user_input is not None:
            show_id = int(user_input[CONF_SHOW_ID])
            if show_id not in {show.tvmaze_id for show in current}:
                return self.async_show_form(
                    step_id="remove_show",
                    data_schema=_show_choice_schema(current),
                    errors={"base": "invalid_selection"},
                )
            return self._save_options(
                tuple(show for show in current if show.tvmaze_id != show_id)
            )
        return self.async_show_form(
            step_id="remove_show", data_schema=_show_choice_schema(current)
        )

    async def async_step_change_match(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which configured show should be rematched."""
        current = _entry_shows(self.config_entry)
        if user_input is not None:
            show_id = int(user_input[CONF_SHOW_ID])
            if show_id not in {show.tvmaze_id for show in current}:
                return self.async_show_form(
                    step_id="change_match",
                    data_schema=_show_choice_schema(current),
                    errors={"base": "invalid_selection"},
                )
            self._change_show_id = show_id
            return await self.async_step_change_match_search()
        return self.async_show_form(
            step_id="change_match", data_schema=_show_choice_schema(current)
        )

    async def async_step_change_match_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search TVmaze for a replacement match."""
        current_show = self._change_show()
        if current_show is None:
            return await self.async_step_change_match()
        errors: dict[str, str] = {}
        placeholders = {"current_show": current_show.canonical_name}
        defaults = {CONF_SHOW_NAME: current_show.entered_name}
        if user_input is not None:
            query = str(user_input[CONF_SHOW_NAME]).strip()
            if not query:
                errors["base"] = "no_shows"
            else:
                candidates, error = await _async_search_candidates(self.hass, query)
                if error:
                    errors["base"] = error
                    placeholders["title"] = query
                else:
                    self._pending_query = query
                    self._pending_candidates = candidates
                    return self._candidate_form("change_match_select")
        return self.async_show_form(
            step_id="change_match_search",
            data_schema=_single_show_schema(user_input or defaults),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_change_match_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the replacement TVmaze match."""
        if (
            self._change_show() is None
            or not self._pending_query
            or not self._pending_candidates
        ):
            return await self.async_step_change_match()
        if user_input is None:
            return self._candidate_form("change_match_select")
        candidate = _candidate_by_id(
            self._pending_candidates, int(user_input[CONF_CANDIDATE_ID])
        )
        if candidate is None:
            return self._candidate_form(
                "change_match_select", {"base": "invalid_selection"}
            )
        current = list(_entry_shows(self.config_entry))
        if any(
            show.tvmaze_id == candidate.tvmaze_id
            and show.tvmaze_id != self._change_show_id
            for show in current
        ):
            return self._candidate_form(
                "change_match_select", {"base": "duplicate_resolved_show"}
            )
        replacement = candidate.as_configured_show(self._pending_query)
        shows = tuple(
            replacement if show.tvmaze_id == self._change_show_id else show
            for show in current
        )
        return self._save_options(shows)

    async def async_step_poll_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change only the polling interval."""
        errors: dict[str, str] = {}
        current = _entry_poll_interval(self.config_entry)
        if user_input is not None:
            interval = int(user_input[CONF_POLL_INTERVAL])
            error = _poll_interval_error(interval)
            if error:
                errors[CONF_POLL_INTERVAL] = error
            else:
                return self._save_options(_entry_shows(self.config_entry), interval)
        return self.async_show_form(
            step_id="poll_interval",
            data_schema=_poll_interval_schema(user_input, current),
            errors=errors,
        )

    def _finish_add(self, candidate: ShowSearchCandidate) -> ConfigFlowResult:
        current = _entry_shows(self.config_entry)
        if candidate.tvmaze_id in {show.tvmaze_id for show in current}:
            return self._candidate_form("add_select", {"base": "duplicate_resolved_show"})
        assert self._pending_query is not None
        return self._save_options(
            (*current, candidate.as_configured_show(self._pending_query))
        )

    def _candidate_form(
        self, step_id: str, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=_candidate_schema(self._pending_candidates),
            errors=errors or {},
            description_placeholders={"title": self._pending_query or ""},
        )

    def _change_show(self) -> ConfiguredShow | None:
        if self._change_show_id is None:
            return None
        return next(
            (
                show
                for show in _entry_shows(self.config_entry)
                if show.tvmaze_id == self._change_show_id
            ),
            None,
        )

    def _save_options(
        self,
        shows: tuple[ConfiguredShow, ...],
        interval: int | None = None,
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            data={
                CONF_SHOWS: [show.as_dict() for show in shows],
                CONF_POLL_INTERVAL: interval
                if interval is not None
                else _entry_poll_interval(self.config_entry),
            }
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


def _single_show_schema(values: dict[str, Any] | None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SHOW_NAME, default=(values or {}).get(CONF_SHOW_NAME, "")
            ): selector.TextSelector()
        }
    )


def _candidate_schema(candidates: list[ShowSearchCandidate]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CANDIDATE_ID): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=str(candidate.tvmaze_id), label=candidate.label
                        )
                        for candidate in candidates
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _show_choice_schema(shows: tuple[ConfiguredShow, ...]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SHOW_ID): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=str(show.tvmaze_id), label=show.canonical_name
                        )
                        for show in shows
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _poll_interval_schema(
    values: dict[str, Any] | None, current: int
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_POLL_INTERVAL,
                default=(values or {}).get(CONF_POLL_INTERVAL, current),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_POLL_INTERVAL_HOURS,
                    max=MAX_POLL_INTERVAL_HOURS,
                    step=24,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="hours",
                )
            )
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


async def _async_search_candidates(
    hass: Any, query: str
) -> tuple[list[ShowSearchCandidate], str | None]:
    client = TVMazeClient(async_get_clientsession(hass))
    try:
        candidates = await client.async_search_shows(query)
    except TVMazeError as err:
        _LOGGER.warning("Failed to resolve TV show title %r: %s", query, err)
        return [], "cannot_connect"
    if not candidates:
        _LOGGER.info("TVmaze returned no result for title %r", query)
        return [], "show_not_found"
    return candidates, None


def _automatic_candidate(
    query: str, candidates: list[ShowSearchCandidate]
) -> ShowSearchCandidate | None:
    if len(candidates) == 1:
        return candidates[0]
    exact = [candidate for candidate in candidates if candidate.name.casefold() == query.casefold()]
    return exact[0] if len(exact) == 1 else None


def _candidate_by_id(
    candidates: list[ShowSearchCandidate], tvmaze_id: int
) -> ShowSearchCandidate | None:
    return next(
        (candidate for candidate in candidates if candidate.tvmaze_id == tvmaze_id), None
    )


def _entry_shows(entry: ConfigEntry) -> tuple[ConfiguredShow, ...]:
    raw = entry.options.get(CONF_SHOWS, entry.data.get(CONF_SHOWS, []))
    return tuple(ConfiguredShow.from_dict(item) for item in raw)


def _entry_poll_interval(entry: ConfigEntry) -> int:
    return int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_HOURS))


def _poll_interval_error(interval: int) -> str | None:
    if interval < MIN_POLL_INTERVAL_HOURS:
        return "poll_interval_too_short"
    if interval > MAX_POLL_INTERVAL_HOURS:
        return "poll_interval_too_long"
    if interval % 24:
        return "poll_interval_invalid_step"
    return None
