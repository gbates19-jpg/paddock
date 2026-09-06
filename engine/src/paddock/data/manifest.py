"""Per-market data-plan manifest, written alongside unpacked historic data.

Plan detection is a byte-scan of the actual content, verified against real
downloads of all three tiers (never trust the filename/tar path — Betfair's
own folder labels are a hint, not ground truth we should depend on):
  - "pro": full order-book depth, literal `atb`/`atl` keys.
  - "advanced": compact best-price-only depth (`batb`/`batl`) plus the
    traded-volume ladder (`trd`) — no full atb/atl.
  - "basic": `ltp` only, none of the above.
flumine's native SimulatedMiddleware matching (fill_model=ladder) is driven
by `trd` (paddock.sim.fill_models), which both pro and advanced provide —
so both satisfy fill_model=ladder. Only basic requires fill_model=ltp_cross.

The manifest is a cache of this (data_plan_for's fast path); files that
never went through unpack() (a hand-dropped file, a bundled test fixture)
have no entry, so data_plan_for() always falls back to direct detection.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

DataPlan = Literal["basic", "advanced", "pro"]

_PRO_MARKERS = (b'"atb"', b'"atl"')
_ADVANCED_MARKERS = (b'"batb"', b'"batl"', b'"trd"')

# fill_model=ladder needs the traded-volume ladder — both richer tiers have it.
LADDER_CAPABLE_PLANS: tuple[DataPlan, ...] = ("advanced", "pro")


def detect_data_plan_bytes(raw: bytes) -> DataPlan:
    if any(marker in raw for marker in _PRO_MARKERS):
        return "pro"
    if any(marker in raw for marker in _ADVANCED_MARKERS):
        return "advanced"
    return "basic"


def detect_data_plan(path: Path) -> DataPlan:
    return detect_data_plan_bytes(Path(path).read_bytes())


def manifest_path(data_root: Path) -> Path:
    return Path(data_root) / "manifest.jsonl"


def load_manifest(data_root: Path) -> dict[str, dict]:
    path = manifest_path(data_root)
    if not path.exists():
        return {}
    entries: dict[str, dict] = {}
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            entries[entry["market_id"]] = entry
    return entries


def append_manifest(data_root: Path, entries: list[dict]) -> None:
    """Append-only — a market unpacked twice just gets two lines, and
    load_manifest's dict-by-market_id naturally keeps the last one."""
    if not entries:
        return
    path = manifest_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def data_plan_for(path: Path, data_root: Path | None = None) -> DataPlan:
    """Manifest lookup (fast path), falling back to direct byte-scan."""
    path = Path(path)
    if data_root is not None:
        entry = load_manifest(data_root).get(path.name)
        if entry and "data_plan" in entry:
            return entry["data_plan"]
    return detect_data_plan(path)
