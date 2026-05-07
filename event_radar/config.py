from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent
EVENT_CONFIG_PATH = ROOT / "config" / "event_radar.yaml"
THEME_MAP_PATH = ROOT / "config" / "theme_map.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def load_event_config(path: Path = EVENT_CONFIG_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def load_theme_map(path: Path = THEME_MAP_PATH) -> dict[str, Any]:
    return _load_yaml(path)

