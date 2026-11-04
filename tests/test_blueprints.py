"""Validate the optional, manually importable Home Assistant blueprints."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


class _BlueprintLoader(yaml.SafeLoader):
    """Parse Home Assistant's !input tag without expanding blueprint inputs."""


def _input(loader: _BlueprintLoader, node: yaml.ScalarNode) -> dict[str, str]:
    return {"blueprint_input": loader.construct_scalar(node)}


_BlueprintLoader.add_constructor("!input", _input)


@pytest.mark.parametrize(
    ("filename", "events"),
    [
        (
            "tv_show_monitor_episode_notification.yaml",
            {"tv_show_monitor_episode_today", "tv_show_monitor_episode_airing"},
        ),
        (
            "tv_show_monitor_schedule_alerts.yaml",
            {"tv_show_monitor_schedule_changed", "tv_show_monitor_status_changed"},
        ),
    ],
)
def test_blueprints_parse_and_use_supported_event_contracts(
    filename: str, events: set[str]
) -> None:
    """Blueprints must remain valid YAML with declared inputs and real event names."""
    path = Path(__file__).parents[1] / "blueprints" / "automation" / filename
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=_BlueprintLoader)

    assert document["blueprint"]["domain"] == "automation"
    inputs = document["blueprint"]["input"]
    assert inputs["notify_entity"]["selector"]["entity"]["filter"][0] == {
        "domain": "notify"
    }
    assert document["actions"][0]["action"] == "notify.send_message"
    assert document["actions"][0]["target"]["entity_id"] == {
        "blueprint_input": "notify_entity"
    }
    assert document["variables"]["selected_show"] == {
        "blueprint_input": "show_filter"
    }
    assert document["mode"] == "queued"

    configured_events = set()
    for trigger in document["triggers"]:
        assert trigger["trigger"] == "event"
        event_type = trigger["event_type"]
        if isinstance(event_type, dict):
            input_name = event_type["blueprint_input"]
            assert input_name in inputs
            configured_events.update(
                option["value"]
                for option in inputs[input_name]["selector"]["select"]["options"]
            )
        else:
            configured_events.add(event_type)
    assert configured_events == events
