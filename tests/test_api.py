"""Tests for the TVmaze API client."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.tv_show_monitor.api import (
    TVMazeClient,
    TVMazeError,
    TVMazeNotFoundError,
    TVMazeRateLimitError,
    TVMazeResponseError,
)


class FakeResponse:
    """Minimal asynchronous aiohttp response double."""

    def __init__(self, status=200, payload=None, *, json_error=None, headers=None):
        self.status = status
        self.payload = payload
        self.json_error = json_error
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeSession:
    """Return queued responses without touching the network."""

    def __init__(self, *responses):
        self.responses = list(responses)

    async def get(self, *args, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


async def test_successful_title_search():
    client = TVMazeClient(
        FakeSession(
            FakeResponse(
                payload=[
                    {
                        "score": 1.0,
                        "show": {
                            "id": 216,
                            "name": "Severance",
                            "url": "https://tvmaze.test/216",
                        },
                    }
                ]
            )
        )
    )
    result = await client.async_search_show("Severance")
    assert result is not None
    assert result.tvmaze_id == 216
    assert result.entered_name == "Severance"


async def test_title_search_candidates_include_disambiguation_metadata():
    client = TVMazeClient(
        FakeSession(
            FakeResponse(
                payload=[
                    {
                        "score": 1.0,
                        "show": {
                            "id": 526,
                            "name": "The Office",
                            "url": "https://tvmaze.test/526",
                            "premiered": "2005-03-24",
                            "status": "Ended",
                            "network": {
                                "name": "NBC",
                                "country": {"name": "United States"},
                            },
                        },
                    },
                    {"score": 0.5, "show": {"id": "bad", "name": "Broken"}},
                ]
            )
        )
    )
    results = await client.async_search_shows("The Office")
    assert len(results) == 1
    assert results[0].tvmaze_id == 526
    assert results[0].premiered == "2005-03-24"
    assert results[0].network == "NBC"
    assert results[0].country == "United States"
    assert results[0].status == "Ended"
    assert results[0].label == "The Office — 2005 · United States · NBC · Ended"


async def test_no_title_search_results():
    assert (
        await TVMazeClient(FakeSession(FakeResponse(payload=[]))).async_search_show(
            "Missing"
        )
        is None
    )


async def test_successful_next_episode(episode):
    payload = {
        "id": 216,
        "name": "Severance",
        "_embedded": {
            "nextepisode": {
                "id": episode.episode_id,
                "name": episode.name,
                "season": episode.season,
                "number": episode.number,
                "type": episode.episode_type,
                "airdate": episode.air_date,
                "airtime": episode.air_time,
                "airstamp": episode.air_stamp,
                "runtime": episode.runtime,
                "url": episode.url,
            }
        },
    }
    result = await TVMazeClient(
        FakeSession(FakeResponse(payload=payload))
    ).async_get_next_episode(216)
    assert result == episode


async def test_show_schedule_includes_lifecycle_outlet_schedule_and_artwork(episode):
    previous = {
        "id": 900,
        "name": "Previous",
        "season": 2,
        "number": 3,
        "type": "regular",
        "airdate": "2026-10-05",
        "airtime": "21:00",
        "airstamp": "2026-10-05T21:00:00+00:00",
        "runtime": 50,
        "url": "https://tvmaze.test/episode/900",
    }
    payload = {
        "id": 216,
        "name": "Severance",
        "status": "Ended",
        "ended": "2026-10-12",
        "network": {"name": "NBC"},
        "webChannel": {"name": "Peacock"},
        "schedule": {"days": ["Thursday"], "time": "22:00"},
        "image": {
            "medium": "https://static.tvmaze.test/severance-medium.jpg",
            "original": "https://static.tvmaze.test/severance-original.jpg",
        },
        "_embedded": {
            "nextepisode": {
                "id": episode.episode_id,
                "name": episode.name,
                "season": episode.season,
                "number": episode.number,
                "type": episode.episode_type,
                "airdate": episode.air_date,
                "airtime": episode.air_time,
                "airstamp": episode.air_stamp,
                "runtime": episode.runtime,
                "url": episode.url,
            },
            "previousepisode": previous,
        },
    }
    result = await TVMazeClient(
        FakeSession(FakeResponse(payload=payload))
    ).async_get_show_schedule(216)
    assert result.show_status == "Ended"
    assert result.next_episode == episode
    assert result.previous_episode is not None
    assert result.previous_episode.episode_id == 900
    assert result.previous_episode.name == "Previous"
    assert result.show_image_url == "https://static.tvmaze.test/severance-medium.jpg"
    assert result.ended_date == "2026-10-12"
    assert result.network_name == "NBC"
    assert result.web_channel_name == "Peacock"
    assert result.schedule_days == ("Thursday",)
    assert result.schedule_time == "22:00"


async def test_show_artwork_falls_back_to_original():
    payload = {
        "id": 216,
        "name": "Severance",
        "image": {"original": "https://static.tvmaze.test/severance-original.jpg"},
    }
    result = await TVMazeClient(
        FakeSession(FakeResponse(payload=payload))
    ).async_get_show_schedule(216)
    assert result.show_image_url == "https://static.tvmaze.test/severance-original.jpg"


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 216, "name": "Severance"},
        {"id": 216, "name": "Severance", "_embedded": {}},
    ],
)
async def test_successful_response_without_next_episode(payload):
    result = await TVMazeClient(
        FakeSession(FakeResponse(payload=payload))
    ).async_get_next_episode(216)
    assert result is None


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, TVMazeError),
        (404, TVMazeNotFoundError),
    ],
)
async def test_non_retryable_http_errors(status, error):
    with pytest.raises(error):
        await TVMazeClient(
            FakeSession(FakeResponse(status=status))
        ).async_get_next_episode(216)


async def test_transient_http_error_retries_then_succeeds():
    payload = {"id": 216, "name": "Severance", "_embedded": {}}
    client = TVMazeClient(
        FakeSession(FakeResponse(status=503), FakeResponse(payload=payload))
    )
    with patch("custom_components.tv_show_monitor.api.asyncio.sleep") as sleep:
        result = await client.async_get_next_episode(216)
    assert result is None
    sleep.assert_awaited_once()


async def test_transient_http_error_retries_once_then_raises():
    client = TVMazeClient(
        FakeSession(FakeResponse(status=500), FakeResponse(status=500))
    )
    with (
        patch("custom_components.tv_show_monitor.api.asyncio.sleep"),
        pytest.raises(TVMazeError, match="HTTP 500"),
    ):
        await client.async_get_next_episode(216)


async def test_http_429_retries_then_raises():
    client = TVMazeClient(
        FakeSession(
            FakeResponse(status=429, headers={"Retry-After": "0"}),
            FakeResponse(status=429),
        )
    )
    with pytest.raises(TVMazeRateLimitError):
        await client.async_get_next_episode(216)


async def test_timeout_retries_once_then_raises():
    with (
        patch("custom_components.tv_show_monitor.api.asyncio.timeout") as timeout,
        patch("custom_components.tv_show_monitor.api.asyncio.sleep") as sleep,
    ):
        timeout.return_value.__aenter__.side_effect = [TimeoutError, TimeoutError]
        with pytest.raises(TVMazeError, match="timed out"):
            await TVMazeClient(FakeSession()).async_get_next_episode(216)
    sleep.assert_awaited_once()


async def test_malformed_json():
    with pytest.raises(TVMazeResponseError, match="invalid JSON"):
        await TVMazeClient(
            FakeSession(FakeResponse(json_error=ValueError("bad")))
        ).async_get_next_episode(216)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"_embedded": []},
        {"id": 216, "name": "Severance", "_embedded": {"nextepisode": []}},
        {"id": 216, "name": "Severance", "_embedded": {"nextepisode": {"id": 1}}},
    ],
)
async def test_unexpected_response_structure(payload):
    with pytest.raises(TVMazeResponseError):
        await TVMazeClient(
            FakeSession(FakeResponse(payload=payload))
        ).async_get_next_episode(216)
