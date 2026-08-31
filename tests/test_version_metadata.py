"""Tests for release metadata consistency."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from custom_components.tv_show_monitor.const import VERSION

ROOT = Path(__file__).parents[1]


def test_release_versions_stay_in_sync() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "tv_show_monitor" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert manifest["version"] == VERSION
    assert pyproject["project"]["version"] == VERSION
