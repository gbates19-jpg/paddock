#!/usr/bin/env python3
"""Read-only Betfair pre-off event study.

Reads Betfair historical JSONL market files without touching the Paddock DB.
Features are computed only from state observed at or before each snapshot:
order-book depth imbalance, cross-runner relative log-price movement, and
traded-volume bursts. Labels use executable opposite-side prices observed by
future horizons and include a 2% commission assumption by default.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import statistics
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_OFFSETS = (300, 180, 120, 60, 30, 15)
HORIZONS = (5, 15, 30, 60)
EPS = 1e-9
MAX_EXECUTABLE_PRICE = 100.0


def _merge_levels(book: dict[float, float], levels: Any) -> None:
    if not isinstance(levels, list):
        return
    for level in levels:
        if not isinstance(level, list) or len(level) < 2:
            continue
        try:
            price, size = float(level[0]), float(level[1])
        except (TypeError, ValueError):
            continue
        if price <= 1.0 or size <= 0:
            book.pop(price, None)
        else:
            book[price] = size


def _best(book: dict[float, float], reverse: bool) -> tuple[float | None, float]:
    usable = [p for p in book if 1.0 < p <= MAX_EXECUTABLE_PRICE]
    if not usable:
        return None, 0.0
    price = (max if reverse else min)(usable)
    return price, book[price]


def _depth(book: dict[float, float], reverse: bool, n: int = 3) -> float:
    return sum(book[p] for p in sorted(book, reverse=reverse)[:n])


def _safe_log_price(price: float | None) -> float | None:
    return math.log(price) if price and price > 1.0 else None


def _net_back_return(entry_back: float, exit_lay: float, commission: float) -> float:
    # £1 back stake: gross profit is exit_lay / entry_back - 1.
    gross = exit_lay / entry_back - 1.0
    return gross - max(gross, 0.0) * commission


def _net_lay_return(entry_lay: float, exit_back: float, commission: float) -> float:
    # £1 lay stake: gross profit is 1 - exit_back / entry_lay.
    gross = 1.0 - exit_back / entry_lay
    return gross - max(gross, 0.0) * commission


def _local_date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()


def _market_definition(obj: dict[str, Any]) -> dict[str, Any] | None:
    for mc in obj.get("mc", []) or []:
        if isinstance(mc, dict) and isinstance(mc.get("marketDefinition"), dict):
            return mc["marketDefinition"]
    return None


def _market_id(obj: dict[str, Any]) -> str | None:
    for mc in obj.get("mc", []) or []:
        if isinstance(mc, dict) and mc.get("id"):
            return str(mc["id"])
    return None


def _state_feature(state: dict[str, Any], now_ms: int) -> dict[str, Any]:
    atb, atl = state["atb"], state["atl"]
    bp, bs = _best(atb, True)
    lp, ls = _best(atl, False)
    back_depth = _depth(atb, True)
    lay_depth = _depth(atl, False)
    imbalance = (back_depth - lay_depth) / max(back_depth + lay_depth, EPS)
    total_traded = sum(state["trd"].values())
    hist = state["vol_hist"]
    hist.append((now_ms, total_traded))
    cutoff30 = now_ms - 30_000
    cutoff300 = now_ms - 300_000
    while len(hist) > 2 and hist[1][0] < cutoff300:
        hist.popleft()
    old30 = hist[0][1] if hist and hist[0][0] <= cutoff30 else None
    old300 = hist[0][1] if hist and hist[0][0] <= cutoff300 else None
    if old30 is None:
        # Find the oldest retained observation at least 30s old.
        for ts, vol in hist:
            if ts <= cutoff30:
                old30 = vol
            else:
                break
    vol30 = max(total_traded - old30, 0.0) if old30 is not None else 0.0
    baseline = (total_traded - old300) / 10.0 if old300 is not None else 0.0
    burst = vol30 / max(baseline, 1e-6) if baseline > 0 else (1.0 if vol30 > 0 else 0.0)
    return {
        "best_back": bp, "best_lay": lp, "back_size": bs, "lay_size": ls,
        "depth_back_3": back_depth, "depth_lay_3": lay_depth,
        "depth_imbalance": imbalance, "traded_volume": total_traded,
        "volume_30s": vol30, "volume_burst_ratio": burst,
        "log_mid": math.log((bp + lp) / 2.0) if bp and lp else None,
    }


def _empty_state() -> dict[str, Any]:
    return {"atb": {}, "atl": {}, "trd": {}, "status": "ACTIVE", "vol_hist": deque()}


def _take_snapshot(states: dict[int, dict[str, Any]], ts: int) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for sid, state in states.items():
        f = _state_feature(state, ts)
        f["status"] = state.get("status", "ACTIVE")
        out[sid] = f
    return out


def parse_market(path: Path, commission: float) -> list[dict[str, Any]]:
    """Parse one market and return one row per runner/snapshot/horizon."""
    states: dict[int, dict[str, Any]] = {}
    runner_names: dict[int, str] = {}
    market_id = path.name
    market_time_ms: int | None = None
    market_date = ""
    definition_seen = False
    wanted: dict[int, dict[str, Any]] = {}
    target_offsets: list[tuple[int, int]] = []
    base_targets: list[int] = []
    event_count = 0
    first_ts = None

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            pt = obj.get("pt")
            if not isinstance(pt, (int, float)):
                continue
            pt = int(pt)
            definition = _market_definition(obj)
            if definition and not definition_seen:
                definition_seen = True
                market_id = str(_market_id(obj) or market_id)
                mt = definition.get("marketTime")
                if mt:
                    dt = datetime.fromisoformat(str(mt).replace("Z", "+00:00"))
                    market_time_ms = int(dt.timestamp() * 1000)
                    market_date = _local_date(str(mt))
                    target_offsets = [(off * 1000, off) for off in SNAPSHOT_OFFSETS]
                    for off_ms, off in target_offsets:
                        base_ts = market_time_ms - off_ms
                        base_targets.append(base_ts)
                        wanted[base_ts] = {"offset": off}
                        for horizon in HORIZONS:
                            wanted.setdefault(base_ts + horizon * 1000, {})
                for r in definition.get("runners", []) or []:
                    try:
                        sid = int(r["id"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    states.setdefault(sid, _empty_state())["status"] = r.get("status", "ACTIVE")
                    runner_names[sid] = str(r.get("name", sid))
            if market_time_ms is None:
                continue
            for mc in obj.get("mc", []) or []:
                if not isinstance(mc, dict):
                    continue
                for rc in mc.get("rc", []) or []:
                    try:
                        sid = int(rc["id"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    state = states.setdefault(sid, _empty_state())
                    for key, dest in (("atb", state["atb"]), ("atl", state["atl"]), ("trd", state["trd"])):
                        _merge_levels(dest, rc.get(key))
                    if "status" in rc:
                        state["status"] = rc["status"]
                event_count += 1
            # A snapshot is the last complete state at or before its target.
            for target in sorted(list(wanted)):
                if target <= pt and "state" not in wanted[target]:
                    wanted[target]["state"] = _take_snapshot(states, pt)
            if first_ts is None:
                first_ts = pt
            # Once past the off time no later update can improve pre-off labels.
            if pt > market_time_ms + 60_000:
                break

    if market_time_ms is None or not wanted:
        return []
    # Fill targets with the final pre-off state if a sparse file had no update exactly before target.
    last_state = _take_snapshot(states, market_time_ms)
    for info in wanted.values():
        info.setdefault("state", last_state)
    rows: list[dict[str, Any]] = []
    for target_ts in sorted(base_targets):
        info = wanted[target_ts]
        base = info["state"]
        if not base:
            continue
        active = {sid: f for sid, f in base.items() if f.get("status") == "ACTIVE" and f.get("log_mid") is not None}
        if not active:
            continue
        median_log = statistics.median(f["log_mid"] for f in active.values())
        liquidity = sum(f["traded_volume"] for f in active.values())
        regime = "low" if liquidity < 1_000 else "medium" if liquidity < 10_000 else "high"
        offset = int(info["offset"])
        for sid, f in active.items():
            row = {
                "market_id": market_id, "date": market_date, "snapshot_sec_to_off": offset,
                "runner_id": sid, "runner_name": runner_names.get(sid, str(sid)),
                "liquidity_regime": regime, "market_traded_volume": liquidity,
                "best_back": f["best_back"], "best_lay": f["best_lay"],
                "spread_ticks_approx": (f["best_lay"] - f["best_back"]) if f["best_back"] and f["best_lay"] else None,
                "depth_imbalance": f["depth_imbalance"], "volume_30s": f["volume_30s"],
                "volume_burst_ratio": f["volume_burst_ratio"],
                "relative_log_mid": f["log_mid"] - median_log,
                "feature_timestamp_ms": target_ts,
                "source_file": str(path), "event_count": event_count,
            }
            for horizon in HORIZONS:
                future = wanted.get(target_ts + horizon * 1000, {}).get("state", {})
                ff = future.get(sid, {})
                row[f"future_back_{horizon}s"] = ff.get("best_back")
                row[f"future_lay_{horizon}s"] = ff.get("best_lay")
                # Conservative executable markout: cross the spread to enter
                # and cross it again to exit.  Using best_back -> future
                # best_lay would manufacture a positive return in a flat
                # market by assuming a passive fill with no queue model.
                if f["best_lay"] and ff.get("best_back"):
                    row[f"net_back_return_{horizon}s"] = _net_back_return(f["best_lay"], ff["best_back"], commission)
                else:
                    row[f"net_back_return_{horizon}s"] = None
                if f["best_back"] and ff.get("best_lay"):
                    row[f"net_lay_return_{horizon}s"] = _net_lay_return(f["best_back"], ff["best_lay"], commission)
                else:
                    row[f"net_lay_return_{horizon}s"] = None
                if f["log_mid"] is not None and ff.get("log_mid") is not None:
                    row[f"relative_log_move_{horizon}s"] = (ff["log_mid"] - median_log) - row["relative_log_mid"]
                else:
                    row[f"relative_log_move_{horizon}s"] = None
            rows.append(row)
    return rows


def discover_files(data_root: Path, limit: int | None, sample: str | None) -> list[Path]:
    files = sorted(p for p in data_root.rglob("1.*") if p.is_file() and p.name[2:].isdigit())
    if sample:
        files = [p for p in files if sample in str(p)]
    return files[:limit] if limit else files


def summarize(rows: list[dict[str, Any]], files: list[Path], commission: float) -> dict[str, Any]:
    def mean(key: str, subset: list[dict[str, Any]]) -> float | None:
        vals = [float(r[key]) for r in subset if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = f"{r['date']}|{r['liquidity_regime']}"
        grouped.setdefault(key, []).append(r)
    groups: dict[str, dict[str, Any]] = {}
    for key, subset in grouped.items():
        date, regime = key.split("|", 1)
        g: dict[str, Any] = {"date": date, "liquidity_regime": regime, "rows": len(subset)}
        for h in HORIZONS:
            g[f"mean_net_back_return_{h}s"] = mean(f"net_back_return_{h}s", subset)
            g[f"mean_net_lay_return_{h}s"] = mean(f"net_lay_return_{h}s", subset)
            g[f"mean_relative_log_move_{h}s"] = mean(f"relative_log_move_{h}s", subset)
        groups[key] = g
    return {
        "study": "paddock_preoff_event_study",
        "read_only": True, "commission_rate": commission,
        "feature_rule": "state at or before snapshot; no future fields in features",
        "executable_price_filter": f"1.0 < price <= {MAX_EXECUTABLE_PRICE}; extreme/no-quote levels treated as unavailable",
        "snapshot_offsets_sec": list(SNAPSHOT_OFFSETS), "label_horizons_sec": list(HORIZONS),
        "markets_requested": len(files), "markets_with_rows": len({r["market_id"] for r in rows}),
        "row_count": len(rows), "group_count": len(groups), "groups": sorted(groups.values(), key=lambda x: (x["date"], x["liquidity_regime"])),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=Path(__file__).parents[1] / "data" / "pro")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sample-path-contains", default=None)
    ap.add_argument("--commission", type=float, default=0.02)
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "event_study_output")
    args = ap.parse_args()
    files = discover_files(args.data_root, args.limit, args.sample_path_contains)
    if not files:
        print("No market files found", file=sys.stderr)
        return 2
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for i, path in enumerate(files, 1):
        try:
            rows.extend(parse_market(path, args.commission))
        except Exception as exc:  # keep a full batch moving, report the exact file
            failures.append({"file": str(path), "error": repr(exc)})
        if i == 1 or i % 25 == 0 or i == len(files):
            print(f"processed {i}/{len(files)} files; rows={len(rows)} failures={len(failures)}", file=sys.stderr)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "event_study_rows.csv"
    json_path = args.out_dir / "event_study_report.json"
    fieldnames = sorted({k for r in rows for k in r})
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)
    report = summarize(rows, files, args.commission)
    report["failures"] = failures
    report["csv"] = str(csv_path)
    report["files"] = [str(p) for p in files]
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report": str(json_path), "csv": str(csv_path), "files": len(files), "rows": len(rows), "failures": len(failures)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
