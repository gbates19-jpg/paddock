"""Per-market data-plan manifest, written alongside unpacked historic data.

Basic Plan (free) historic files carry `ltp` only. Advanced/Pro plan files
(and any live stream) also carry `atb`/`atl` (order-book depth) and `trd`
(traded-volume ladder) — flumine's native simulated matching needs the
latter (see paddock.sim.fill_models). detect_data_plan() is the ground
truth (byte-scans the actual file); the manifest is a cache of that so
`sim run` doesn't re-scan every file on every run. Files that never went
through unpack() (a hand-dropped file, a bundled test fixture) won't have a
manifest entry — data_plan_for() falls back to direct detection for those,
so the manifest is never the sole source of truth.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

DataPlan = Literal["basic", "rich"]

_RICH_MARKERS = (b'"atb"', b'"atl"', b'"trd"')


def detect_data_plan(path: Path) -> DataPlan:
    raw = Path(path).read_bytes()
    return "rich" if any(marker in raw for marker in _RICH_MARKERS) else "basic"


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
