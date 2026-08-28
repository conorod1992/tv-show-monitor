"""Constants and typed models for TV Show Monitor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

DOMAIN = "tv_show_monitor"
NAME = "TV Show Monitor"
VERSION = "1.0.0"
API_BASE_URL = "https://api.tvmaze.com"
USER_AGENT = "TV-Show-Monitor/HomeAssistant"
DEFAULT_POLL_INTERVAL_HOURS = 24
MIN_POLL_INTERVAL_HOURS = 24
MAX_POLL_INTERVAL_HOURS = 24 * 31
MAX_SHOWS = 50
MISSING_SHOW_404_THRESHOLD = 3
ENDED_RECHECK_DAYS = 30
CONF_SHOWS = "shows"
CONF_SHOW_NAMES = "show_names"
CONF_POLL_INTERVAL = "poll_interval_hours"
PLATFORMS = ["sensor"]
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}.state"
NO_NEXT_EPISODE = "No next episode found"
EVENT_SCHEDULE_CHANGED = f"{DOMAIN}_schedule_changed"
EVENT_EPISODE_TODAY = f"{DOMAIN}_episode_today"
EVENT_EPISODE_AIRING = f"{DOMAIN}_episode_airing"
EVENT_STATUS_CHANGED = f"{DOMAIN}_status_changed"


@dataclass(frozen=True, slots=True)
class ConfiguredShow:
    """A TVmaze show selected by the user."""

    tvmaze_id: int
    canonical_name: str
    entered_name: str
    show_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ConfiguredShow:
        """Create a configured show from stored config-entry data."""
        return cls(
            tvmaze_id=int(value["tvmaze_id"]),
            canonical_name=str(value["canonical_name"]),
            entered_name=str(value["entered_name"]),
            show_url=str(value["show_url"]) if value.get("show_url") else None,
        )


@dataclass(frozen=True, slots=True)
class EpisodeInfo:
    """A scheduled TVmaze episode."""

    episode_id: int
    name: str
    season: int | None
    number: int | None
    episode_type: str | None
    air_date: str
    air_time: str | None
    air_stamp: str | None
    runtime: int | None
    url: str | None

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EpisodeInfo:
        """Create episode information from storage."""
        return cls(
            episode_id=int(value["episode_id"]),
            name=str(value["name"]),
            season=_optional_int(value.get("season")),
            number=_optional_int(value.get("number")),
            episode_type=_optional_str(value.get("episode_type")),
            air_date=str(value["air_date"]),
            air_time=_optional_str(value.get("air_time")),
            air_stamp=_optional_str(value.get("air_stamp")),
            runtime=_optional_int(value.get("runtime")),
            url=_optional_str(value.get("url")),
        )


@dataclass(frozen=True, slots=True)
class ShowScheduleInfo:
    """Current TVmaze schedule information for a show."""

    show_status: str | None
    next_episode: EpisodeInfo | None
    previous_episode: EpisodeInfo | None
    show_image_url: str | None = None
    ended_date: str | None = None
    network_name: str | None = None
    web_channel_name: str | None = None
    schedule_days: tuple[str, ...] = ()
    schedule_time: str | None = None


@dataclass(frozen=True, slots=True)
class LastKnownState:
    """Persisted last-known state and latest refresh diagnostics."""

    has_successful_value: bool = False
    episode: EpisodeInfo | None = None
    last_successful_update: str | None = None
    last_update_attempt: str | None = None
    last_attempt_successful: bool | None = None
    last_error: str | None = None
    show_status: str | None = None
    previous_episode: EpisodeInfo | None = None
    show_image_url: str | None = None
    consecutive_not_found: int = 0
    ended_date: str | None = None
    network_name: str | None = None
    web_channel_name: str | None = None
    schedule_days: tuple[str, ...] = ()
    schedule_time: str | None = None
    episode_today_fired_key: str | None = None
    episode_airing_fired_key: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable representation."""
        value = asdict(self)
        value["episode"] = self.episode.as_dict() if self.episode else None
        value["previous_episode"] = (
            self.previous_episode.as_dict() if self.previous_episode else None
        )
        value["schedule_days"] = list(self.schedule_days)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LastKnownState:
        """Create state from storage."""
        episode = value.get("episode")
        previous_episode = value.get("previous_episode")
        consecutive_not_found = value.get("consecutive_not_found", 0)
        schedule_days = value.get("schedule_days", [])
        if not isinstance(schedule_days, list) or not all(
            isinstance(day, str) for day in schedule_days
        ):
            schedule_days = []
        return cls(
            has_successful_value=bool(value.get("has_successful_value", False)),
            episode=EpisodeInfo.from_dict(episode)
            if isinstance(episode, dict)
            else None,
            last_successful_update=_optional_str(value.get("last_successful_update")),
            last_update_attempt=_optional_str(value.get("last_update_attempt")),
            last_attempt_successful=value.get("last_attempt_successful"),
            last_error=_optional_str(value.get("last_error")),
            show_status=_optional_str(value.get("show_status")),
            previous_episode=EpisodeInfo.from_dict(previous_episode)
            if isinstance(previous_episode, dict)
            else None,
            show_image_url=_optional_str(value.get("show_image_url")),
            consecutive_not_found=max(0, int(consecutive_not_found)),
            ended_date=_optional_str(value.get("ended_date")),
            network_name=_optional_str(value.get("network_name")),
            web_channel_name=_optional_str(value.get("web_channel_name")),
            schedule_days=tuple(schedule_days),
            schedule_time=_optional_str(value.get("schedule_time")),
            episode_today_fired_key=_optional_str(value.get("episode_today_fired_key")),
            episode_airing_fired_key=_optional_str(
                value.get("episode_airing_fired_key")
            ),
        )


@dataclass(frozen=True, slots=True)
class ShowUpdateResult:
    """The complete entity-facing result for one show."""

    show: ConfiguredShow
    state: LastKnownState


def utc_now_iso() -> str:
    """Return an ISO timestamp in UTC for persistent diagnostics."""
    return datetime.now(UTC).isoformat()


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None
