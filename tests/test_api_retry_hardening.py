"""Regression tests for TVmaze retry timing and transport failures."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp import ClientConnectionError

from custom_components.tv_show_monitor.api import TVMazeClient, TVMazeError


class FakeResponse:
    """Minimal asynchronous aiohttp response double."""

    def __init__(self, status=200, payload=None, *, headers=None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    """Return queued responses or transport errors without network access."""

    def __init__(self, *responses):
        self.responses = list(responses)

    async def get(self, *args, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class TimeoutTracker:
    """Track whether retry backoff accidentally runs inside a request timeout."""

    def __init__(self):
        self.active = False
        self.delays: list[float] = []

    def __call__(self, _seconds):
        return self

    async def __aenter__(self):
        assert self.active is False
        self.active = True
        return self

    async def __aexit__(self, *args):
        self.active = False
        return None

    async def sleep(self, delay):
        assert self.active is False
        self.delays.append(delay)


def _show_payload():
    return {"id": 216, "name": "Severance", "_embedded": {}}


async def test_rate_limit_backoff_runs_outside_request_timeout():
    tracker = TimeoutTracker()
    client = TVMazeClient(
        FakeSession(
            FakeResponse(status=429, headers={"Retry-After": "30"}),
            FakeResponse(payload=_show_payload()),
        )
    )

    with (
        patch("custom_components.tv_show_monitor.api.asyncio.timeout", new=tracker),
        patch("custom_components.tv_show_monitor.api.asyncio.sleep", new=tracker.sleep),
    ):
        result = await client.async_get_next_episode(216)

    assert result is None
    assert tracker.delays == [30.0]


async def test_server_error_backoff_runs_outside_request_timeout():
    tracker = TimeoutTracker()
    client = TVMazeClient(
        FakeSession(
            FakeResponse(status=503),
            FakeResponse(payload=_show_payload()),
        )
    )

    with (
        patch("custom_components.tv_show_monitor.api.asyncio.timeout", new=tracker),
        patch("custom_components.tv_show_monitor.api.asyncio.sleep", new=tracker.sleep),
    ):
        result = await client.async_get_next_episode(216)

    assert result is None
    assert tracker.delays == [1.0]


async def test_client_error_retries_once_then_succeeds():
    tracker = TimeoutTracker()
    client = TVMazeClient(
        FakeSession(
            ClientConnectionError("connection reset"),
            FakeResponse(payload=_show_payload()),
        )
    )

    with (
        patch("custom_components.tv_show_monitor.api.asyncio.timeout", new=tracker),
        patch("custom_components.tv_show_monitor.api.asyncio.sleep", new=tracker.sleep),
    ):
        result = await client.async_get_next_episode(216)

    assert result is None
    assert tracker.delays == [1.0]


async def test_client_error_retries_once_then_raises():
    tracker = TimeoutTracker()
    client = TVMazeClient(
        FakeSession(
            ClientConnectionError("connection reset"),
            ClientConnectionError("connection reset again"),
        )
    )

    with (
        patch("custom_components.tv_show_monitor.api.asyncio.timeout", new=tracker),
        patch("custom_components.tv_show_monitor.api.asyncio.sleep", new=tracker.sleep),
        pytest.raises(TVMazeError, match="Unable to communicate with TVmaze"),
    ):
        await client.async_get_next_episode(216)

    assert tracker.delays == [1.0]
