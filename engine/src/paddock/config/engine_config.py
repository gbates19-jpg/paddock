"""Loads engine-wide tunables from config/engine.yaml.

Kept separate from Settings (env/.env, secrets + mode) — this is checked-in,
non-secret configuration. Path is resolved relative to this file's location
(engine/config/engine.yaml), not the process cwd, so it works regardless of
where `paddock` is invoked from (the repo path contains spaces).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

DEFAULT_COMMISSION_RATE = 0.02

# "ladder": flumine's native traded-volume-ladder matching. Requires
# ex/trd fields (Advanced/Pro plan or live stream) — see
# paddock.sim.fill_models and paddock.data.historic.detect_data_plan.
# "ltp_cross": documented optimistic approximation for Basic Plan
# (ltp-only) data.
FillModel = Literal["ladder", "ltp_cross"]
DEFAULT_FILL_MODEL: FillModel = "ladder"

# engine/src/paddock/config/engine_config.py -> parents[3] == engine/
_ENGINE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENGINE_CONFIG_PATH = _ENGINE_ROOT / "config" / "engine.yaml"


class EngineConfig(BaseModel):
    commission_rate: float = DEFAULT_COMMISSION_RATE
    fill_model: FillModel = DEFAULT_FILL_MODEL


def _config_path() -> Path:
    override = os.environ.get("PADDOCK_ENGINE_CONFIG")
    return Path(override) if override else DEFAULT_ENGINE_CONFIG_PATH


def load_engine_config(path: Path | None = None) -> EngineConfig:
    config_path = path or _config_path()
    if not config_path.exists():
        return EngineConfig()
    with config_path.open("r") as f:
        data = yaml.safe_load(f) or {}
    return EngineConfig.model_validate(data)
