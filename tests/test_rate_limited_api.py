"""Tests for coordinator TVmaze request pacing."""

from __future__ import annotations

from unittest.mock import patch

from custom_components.tv_show_monitor.rate_limited_api import (
    MIN_REQUEST_INTERVAL,
    RateLimitedTVMazeClient,
)


class FakeClock:
    """Deterministic monotonic clock advanced by fake sleeps."""

    def __init__(self) -> None:
        self.now = 100.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


async def test_request_slots_are_spaced_at_safe_interval() -> None:
    clock = FakeClock()
    client = RateLimitedTVMazeClient(None)  # type: ignore[arg-type]

    with (
        patch(
            "custom_components.tv_show_monitor.rate_limited_api.time.monotonic",
            new=clock.monotonic,
        ),
        patch(
            "custom_components.tv_show_monitor.rate_limited_api.asyncio.sleep",
            new=clock.sleep,
        ),
    ):
        await client._async_wait_for_request_slot()
        await client._async_wait_for_request_slot()
        await client._async_wait_for_request_slot()

    assert clock.delays == [MIN_REQUEST_INTERVAL, MIN_REQUEST_INTERVAL]


async def test_elapsed_time_does_not_add_unnecessary_delay() -> None:
    clock = FakeClock()
    client = RateLimitedTVMazeClient(None)  # type: ignore[arg-type]

    with (
        patch(
            "custom_components.tv_show_monitor.rate_limited_api.time.monotonic",
            new=clock.monotonic,
        ),
        patch(
            "custom_components.tv_show_monitor.rate_limited_api.asyncio.sleep",
            new=clock.sleep,
        ),
    ):
        await client._async_wait_for_request_slot()
        clock.now += MIN_REQUEST_INTERVAL
        await client._async_wait_for_request_slot()

    assert clock.delays == []
