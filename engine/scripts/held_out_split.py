"""Leakage-safe calibration/held-out split for the strategy-research
batch (see docs/strategy-research.md).

Why this exists: a reviewer (Jeff) correctly flagged that docs/run-plan.md's
40-market pilot sample sat INSIDE the final 989-market evaluation batch,
and every strategy's calibration in docs/strategy-research.md (the
favourite-longshot lay threshold, the drift z-score window, the market
maker's spread rule) was chosen after inspecting samples drawn from that
same population — the same data shaped both what got built and how it
was scored. That doesn't make the arithmetic wrong, but it means "no
exploitable edge on this data" was claimed at more confidence than the
methodology actually supports. This module fixes the methodology going
forward: a real train/test partition, decided once, from date boundaries
alone, before anything is re-evaluated on it.

Partitioned by DATE (whole race days, in Europe/London local time — a
market's `market_time` in the manifest is UTC, and Aug 2015 is BST
(UTC+1), so a naive UTC-date split would occasionally misclassify a
last-race-of-the-day market into the next calendar day). Never split a
single day across the two slices — meetings on the same day can share a
common regime (going conditions, weather, the same trainers/tracks
running), so a mid-day split would leak in a subtler way than it first
looks.

The boundary below is fixed and was chosen ONLY by looking at the
cumulative date/market-count table (no strategy performance numbers were
consulted) to land near the requested 15-20% calibration share:

    calibration: 2015-07-31 .. 2015-08-06  (7 days,  189 markets, 19.1%)
    held_out:    2015-08-07 .. 2015-08-31  (25 days, 800 markets, 80.9%)

From the point this split was drawn, `held_out_market_files()` is what
every strategy's *reported* verdict must be evaluated on — no further
tuning against it, no re-inspecting its aggregate stats to adjust a
parameter. `calibration_market_files()` is there so old and new
calibration work can be re-run against the same slice if needed, not for
scoring anything.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_UTC = ZoneInfo("UTC")
_LONDON = ZoneInfo("Europe/London")

# engine/scripts/held_out_split.py -> parents[1] == engine/ -> ../data
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = _REPO_ROOT / "data"
DEFAULT_PRO_ROOT = DEFAULT_DATA_ROOT / "pro" / "2015"

CALIBRATION_DATES = frozenset(
    {"2015-07-31", "2015-08-01", "2015-08-02", "2015-08-03", "2015-08-04", "2015-08-05", "2015-08-06"}
)


def _local_date(market_time_iso: str) -> str:
    dt_utc = datetime.fromisoformat(market_time_iso.replace("Z", "+00:00")).replace(tzinfo=_UTC)
    return dt_utc.astimezone(_LONDON).date().isoformat()


def _market_ids_by_slice(data_root: Path) -> tuple[set[str], set[str]]:
    """Returns (calibration_market_ids, held_out_market_ids), read fresh
    from manifest.jsonl every call — this is a one-off research split,
    not something worth caching/hardcoding as a market_id list."""
    calibration: set[str] = set()
    held_out: set[str] = set()
    manifest_path = data_root / "manifest.jsonl"
    with manifest_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("data_plan") != "pro" or entry.get("market_type") != "WIN":
                continue
            date = _local_date(entry["market_time"])
            target = calibration if date in CALIBRATION_DATES else held_out
            target.add(entry["market_id"])
    return calibration, held_out


def _resolve_files(market_ids: set[str], pro_root: Path) -> list[Path]:
    files = [p for p in pro_root.rglob("*") if p.is_file() and p.name in market_ids]
    found_ids = {p.name for p in files}
    missing = market_ids - found_ids
    if missing:
        raise FileNotFoundError(f"{len(missing)} market_id(s) in manifest but not found under {pro_root}: "
                                 f"{sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}")
    return sorted(files)


def calibration_market_files(data_root: Path = DEFAULT_DATA_ROOT, pro_root: Path = DEFAULT_PRO_ROOT) -> list[Path]:
    calibration_ids, _ = _market_ids_by_slice(data_root)
    return _resolve_files(calibration_ids, pro_root)


def held_out_market_files(data_root: Path = DEFAULT_DATA_ROOT, pro_root: Path = DEFAULT_PRO_ROOT) -> list[Path]:
    _, held_out_ids = _market_ids_by_slice(data_root)
    return _resolve_files(held_out_ids, pro_root)


if __name__ == "__main__":
    cal = calibration_market_files()
    held = held_out_market_files()
    print(f"calibration: {len(cal)} markets")
    print(f"held_out:    {len(held)} markets")
    print(f"total:       {len(cal) + len(held)} markets")
