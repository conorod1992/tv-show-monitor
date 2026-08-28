"""Shared TV Show Monitor test fixtures."""

from __future__ import annotations

from collections.abc import Callable, Generator
from unittest.mock import patch

import pytest

from custom_components.tv_show_monitor.const import ConfiguredShow, EpisodeInfo


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations,
) -> Generator[None]:
    """Enable custom integrations in the Home Assistant test harness."""
    yield


@pytest.fixture(autouse=True)
def block_tvmaze_network() -> Generator[None]:
    """Fail immediately if a test accidentally creates a real API session."""
    with patch(
        "custom_components.tv_show_monitor.api.ClientSession",
        autospec=True,
    ):
        yield


@pytest.fixture(autouse=True)
def isolate_coordinator_unit_test_timers(request, monkeypatch) -> Generator[None]:
    """Avoid real timers in coordinator tests that call internals without unloading."""
    if request.node.path.name != "test_coordinator.py":
        yield
        return

    def noop_tracker(*_args, **_kwargs) -> Callable[[], None]:
        return lambda: None

    monkeypatch.setattr(
        "custom_components.tv_show_monitor.coordinator.async_track_point_in_time",
        noop_tracker,
    )
    monkeypatch.setattr(
        "custom_components.tv_show_monitor.coordinator.async_track_time_change",
        noop_tracker,
    )
    yield


@pytest.fixture
def severance() -> ConfiguredShow:
    """Return a configured show."""
    return ConfiguredShow(216, "Severance", "Severance", "https://tvmaze.test/216")


@pytest.fixture
def episode() -> EpisodeInfo:
    """Return a complete episode."""
    return EpisodeInfo(
        12345,
        "Hello, Ms. Cobel",
        2,
        4,
        "regular",
        "2026-10-12",
        "21:00",
        "2026-10-12T20:00:00+00:00",
        52,
        "https://tvmaze.test/episodes/12345",
    )
