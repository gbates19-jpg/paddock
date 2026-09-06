"""Loads per-strategy parameters from config/strategies.yaml, keyed by the
name registered in paddock.strategies.registry. Mirrors engine_config.py's
path resolution (anchored to this file's location, not cwd)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

_ENGINE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STRATEGIES_CONFIG_PATH = _ENGINE_ROOT / "config" / "strategies.yaml"


def _config_path() -> Path:
    override = os.environ.get("PADDOCK_STRATEGIES_CONFIG")
    return Path(override) if override else DEFAULT_STRATEGIES_CONFIG_PATH


def load_strategy_params(name: str, path: Path | None = None) -> dict:
    config_path = path or _config_path()
    if not config_path.exists():
        return {}
    with config_path.open("r") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get(name, {}))
