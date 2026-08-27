"""Asynchronous TVmaze API client."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import API_BASE_URL, USER_AGENT, ConfiguredShow, EpisodeInfo

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = 15
MAX_RETRIES = 1
MAX_RETRY_AFTER = 30.0
RETRY_DELAY = 1.0
RETRYABLE_STATUSES = {500, 502, 503, 504}
MAX_SEARCH_CANDIDATES = 10


class TVMazeError(Exception):
    """Base error for TVmaze communication and response validation."""


class TVMazeNotFoundError(TVMazeError):
    """A show or API resource was not found."""


class TVMazeRateLimitError(TVMazeError):
    """TVmaze continued rate-limiting after retry."""


class TVMazeResponseError(TVMazeError):
    """TVmaze returned malformed or unexpected data."""


@dataclass(frozen=True, slots=True)
class ShowSearchCandidate:
    """A TVmaze search result with enough metadata for user disambiguation."""

    tvmaze_id: int
    name: str
    url: str | None
    premiered: str | None
    status: str | None
    network: str | None
    country: str | None

    def as_configured_show(self, entered_name: str) -> ConfiguredShow:
        """Convert this candidate into persistent configuration."""
        return ConfiguredShow(self.tvmaze_id, self.name, entered_name, self.url)

    @property
    def label(self) -> str:
        """Return a compact human-readable candidate label."""
        details: list[str] = []
        if self.premiered:
            details.append(self.premiered[:4])
        if self.country:
            details.append(self.country)
        if self.network:
            details.append(self.network)
        if self.status:
            details.append(self.status)
        return f"{self.name} — {' · '.join(details)}" if details else self.name


class TVMazeClient:
    """Small typed client using Home Assistant's shared aiohttp session."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def async_search_shows(self, query: str) -> list[ShowSearchCandidate]:
        """Return ranked TVmaze search candidates for a title."""
        payload = await self._async_get("/search/shows", params={"q": query})
        if not isinstance(payload, list):
            raise TVMazeResponseError("Unexpected title-search response")

        candidates: list[ShowSearchCandidate] = []
        for item in payload[:MAX_SEARCH_CANDIDATES]:
            if not isinstance(item, dict) or not isinstance(item.get("show"), dict):
                continue
            show = item["show"]
            show_id = show.get("id")
            name = show.get("name")
            if (
                not isinstance(show_id, int)
                or not isinstance(name, str)
                or not name.strip()
            ):
                continue
            url = show.get("url")
            if url is not None and not isinstance(url, str):
                url = None
            candidates.append(
                ShowSearchCandidate(
                    tvmaze_id=show_id,
                    name=name.strip(),
                    url=url,
                    premiered=_optional_str_loose(show.get("premiered")),
                    status=_optional_str_loose(show.get("status")),
                    network=_show_network_name(show),
                    country=_show_country_name(show),
                )
            )
        return candidates

    async def async_search_show(self, query: str) -> ConfiguredShow | None:
        """Resolve a title to TVmaze's highest-ranked search result."""
        candidates = await self.async_search_shows(query)
        return candidates[0].as_configured_show(query) if candidates else None

    async def async_get_next_episode(self, tvmaze_id: int) -> EpisodeInfo | None:
        """Return the next episode, or None after a valid no-episode response."""
        payload = await self._async_get(
            f"/shows/{tvmaze_id}", params={"embed": "nextepisode"}
        )
        if not isinstance(payload, dict):
            raise TVMazeResponseError("Unexpected show response")
        if payload.get("id") != tvmaze_id or not isinstance(payload.get("name"), str):
            raise TVMazeResponseError("Show response is missing required data")
        embedded = payload.get("_embedded")
        if embedded is None:
            return None
        if not isinstance(embedded, dict):
            raise TVMazeResponseError("Invalid embedded episode data")
        episode = embedded.get("nextepisode")
        if episode is None:
            return None
        if not isinstance(episode, dict):
            raise TVMazeResponseError("Invalid next-episode data")
        episode_id = episode.get("id")
        name = episode.get("name")
        air_date = episode.get("airdate")
        if (
            not isinstance(episode_id, int)
            or not isinstance(name, str)
            or not isinstance(air_date, str)
            or not air_date
        ):
            raise TVMazeResponseError("Next episode is missing required data")
        return EpisodeInfo(
            episode_id=episode_id,
            name=name,
            season=_optional_int(episode, "season"),
            number=_optional_int(episode, "number"),
            episode_type=_optional_str(episode, "type"),
            air_date=air_date,
            air_time=_optional_str(episode, "airtime"),
            air_stamp=_optional_str(episode, "airstamp"),
            runtime=_optional_int(episode, "runtime"),
            url=_optional_str(episode, "url"),
        )

    async def _async_get(self, path: str, *, params: dict[str, str]) -> Any:
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    response = await self._session.get(
                        f"{API_BASE_URL}{path}",
                        params=params,
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "application/json",
                        },
                    )
                    async with response:
                        if response.status == 429:
                            if attempt < MAX_RETRIES:
                                delay = _retry_delay(response)
                                _LOGGER.warning(
                                    "TVmaze rate limited a request; retrying in %.1f seconds",
                                    delay,
                                )
                                await asyncio.sleep(delay)
                                continue
                            raise TVMazeRateLimitError("TVmaze rate limit exceeded")
                        if response.status in RETRYABLE_STATUSES:
                            if attempt < MAX_RETRIES:
                                _LOGGER.warning(
                                    "TVmaze returned HTTP %s; retrying once",
                                    response.status,
                                )
                                await asyncio.sleep(RETRY_DELAY)
                                continue
                            raise TVMazeError(f"TVmaze returned HTTP {response.status}")
                        if response.status == 404:
                            raise TVMazeNotFoundError("TVmaze resource not found")
                        if response.status >= 400:
                            raise TVMazeError(f"TVmaze returned HTTP {response.status}")
                        try:
                            return await response.json()
                        except (ValueError, TypeError) as err:
                            raise TVMazeResponseError(
                                "TVmaze returned invalid JSON"
                            ) from err
            except TimeoutError as err:
                if attempt < MAX_RETRIES:
                    _LOGGER.warning("TVmaze request timed out; retrying once")
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                raise TVMazeError("TVmaze request timed out") from err
            except ClientError as err:
                raise TVMazeError("Unable to communicate with TVmaze") from err
        raise TVMazeRateLimitError("TVmaze rate limit exceeded")


def _retry_delay(response: ClientResponse) -> float:
    value = response.headers.get("Retry-After")
    if not value:
        return RETRY_DELAY
    try:
        return min(MAX_RETRY_AFTER, max(0.0, float(value)))
    except ValueError:
        try:
            delay = (
                parsedate_to_datetime(value)
                - parsedate_to_datetime(response.headers["Date"])
            ).total_seconds()
            return min(MAX_RETRY_AFTER, max(0.0, delay))
        except KeyError, TypeError, ValueError:
            return RETRY_DELAY


def _show_network_name(show: dict[str, Any]) -> str | None:
    for key in ("network", "webChannel"):
        value = show.get(key)
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str):
                return name
    return None


def _show_country_name(show: dict[str, Any]) -> str | None:
    for key in ("network", "webChannel"):
        value = show.get(key)
        if not isinstance(value, dict):
            continue
        country = value.get("country")
        if isinstance(country, dict):
            name = country.get("name")
            if isinstance(name, str):
                return name
    return None


def _optional_str_loose(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise TVMazeResponseError(f"Next episode contains invalid {key}")
    return value


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TVMazeResponseError(f"Next episode contains invalid {key}")
    return value
