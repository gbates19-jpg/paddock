#!/usr/bin/env python3
"""Sealed September archive inventory and corrected quote-markout evaluation.

The tar and its bzip2 members are streamed read-only. No archive member is
rewritten or extracted persistently. September is never used for calibration.
"""
from __future__ import annotations

import bz2
import csv
import hashlib
import json
import tarfile
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from research.event_study import HORIZONS, parse_market

ARCHIVE = Path("/Volumes/Mac Mini 2TB/projects/BetFair/data/raw/data.tar")
ALLOWED_COUNTRIES = {"GB", "IE"}
ALLOWED_MARKET_TYPE = "WIN"


def archive_fingerprint(path: Path) -> dict[str, Any]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            size += len(chunk)
            h.update(chunk)
    return {"path": str(path), "bytes": size, "sha256": h.hexdigest()}


def _market_definitions(obj: dict[str, Any]):
    for mc in obj.get("mc", []) or []:
        if isinstance(mc, dict) and isinstance(mc.get("marketDefinition"), dict):
            yield mc.get("id"), mc["marketDefinition"]


def scan_inventory(path: Path) -> dict[str, Any]:
    members = 0
    compressed_members = 0
    member_roles = Counter()
    market_members: dict[str, list[str]] = defaultdict(list)
    market_meta: dict[str, dict[str, Any]] = {}
    countries = Counter()
    market_types = Counter()
    dates: list[str] = []
    failures: list[dict[str, str]] = []
    total_lines = 0

    with tarfile.open(path, "r|") as tf:
        for member in tf:
            members += 1
            if not member.isfile() or not member.name.endswith(".bz2"):
                member_roles["non_bz2"] += 1
                continue
            compressed_members += 1
            role = "market_file" if member.name.rsplit("/", 1)[-1].startswith("1.") else "event_file"
            member_roles[role] += 1
            seen_market_ids: set[str] = set()
            last_pt: int | None = None
            try:
                with bz2.BZ2File(tf.extractfile(member)) as stream:
                    for raw in stream:
                        total_lines += 1
                        try:
                            obj = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            failures.append({"member": member.name, "error": f"json:{exc.msg}"})
                            continue
                        pt = obj.get("pt")
                        if isinstance(pt, (int, float)):
                            pt = int(pt)
                            if last_pt is not None and pt < last_pt:
                                failures.append({"member": member.name, "error": f"out_of_order_pt:{pt}<{last_pt}"})
                            last_pt = pt
                        for raw_id, definition in _market_definitions(obj):
                            if raw_id is None:
                                continue
                            market_id = str(raw_id)
                            seen_market_ids.add(market_id)
                            market_members[market_id].append(member.name)
                            if market_id not in market_meta:
                                market_meta[market_id] = {
                                    "market_id": market_id,
                                    "country_code": definition.get("countryCode"),
                                    "market_type": definition.get("marketType"),
                                    "market_time": definition.get("marketTime"),
                                    "event_id": definition.get("eventId"),
                                    "event_name": definition.get("eventName"),
                                    "market_name": definition.get("name"),
                                    "bet_delay": definition.get("betDelay"),
                                }
            except Exception as exc:
                failures.append({"member": member.name, "error": f"stream:{exc!r}"})
            if not seen_market_ids:
                member_roles["no_market_definition"] += 1

    # Count the frozen market population once per distinct market ID, not once
    # per repeated definition or event-level duplicate member.
    for meta in market_meta.values():
        countries[str(meta.get("country_code") or "<missing>")] += 1
        market_types[str(meta.get("market_type") or "<missing>")] += 1
        if meta.get("market_time"):
            dates.append(str(meta["market_time"]))

    duplicate_ids = {mid: sorted(set(names)) for mid, names in market_members.items() if len(set(names)) > 1}
    eligible = {
        mid: meta for mid, meta in market_meta.items()
        if meta.get("country_code") in ALLOWED_COUNTRIES and meta.get("market_type") == ALLOWED_MARKET_TYPE
    }
    canonical: dict[str, str] = {}
    for mid in eligible:
        exact = [name for name in set(market_members[mid]) if name.rsplit("/", 1)[-1] == f"{mid}.bz2"]
        canonical[mid] = sorted(exact or set(market_members[mid]))[0]

    return {
        "inventory_version": "september-2026-v1",
        "archive": archive_fingerprint(path),
        "member_count": members,
        "compressed_members": compressed_members,
        "member_roles": dict(member_roles),
        "json_lines": total_lines,
        "parser_failures": failures,
        "date_range": {"min": min(dates) if dates else None, "max": max(dates) if dates else None},
        "country_counts_distinct_market_ids": dict(countries),
        "market_type_counts_distinct_market_ids": dict(market_types),
        "distinct_market_ids": len(market_meta),
        "duplicate_market_id_count": len(duplicate_ids),
        "overlap_member_count": len({name for names in duplicate_ids.values() for name in names}),
        "duplicate_or_overlapping_markets": duplicate_ids,
        "eligible_market_count": len(eligible),
        "excluded_market_count": len(market_meta) - len(eligible),
        "exclusions": {
            "country": "only GB and IE retained",
            "market_type": "only WIN retained",
            "other_countries_and_types_remain_in_inventory": True,
            "canonical_selection": "one exact 1.<market_id>.bz2 member per eligible market; duplicate event/member views excluded",
        },
        "market_meta": market_meta,
        "canonical_members": canonical,
    }


def evaluate(path: Path, inventory: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical = inventory["canonical_members"]
    target_members = set(canonical.values())
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    member_meta = {mid: inventory["market_meta"][mid] for mid in canonical}

    with tarfile.open(path, "r|") as tf:
        for member in tf:
            if member.name not in target_members:
                continue
            try:
                with bz2.BZ2File(tf.extractfile(member)) as stream, tempfile.NamedTemporaryFile(suffix=".jsonl") as tmp:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        tmp.write(chunk)
                    tmp.flush()
                    parsed = parse_market(Path(tmp.name), commission=0.02)
                market_id = next(mid for mid, name in canonical.items() if name == member.name)
                meta = member_meta[market_id]
                for wide in parsed:
                    for horizon in HORIZONS:
                        future_ts = wide.get(f"future_state_timestamp_ms_{horizon}s")
                        if not isinstance(future_ts, int):
                            continue
                        if not isinstance(wide.get("feature_state_timestamp_ms"), int):
                            continue
                        rows.append({
                            "result_kind": "quote_markout",
                            "simulated_fill": False,
                            "strategy_pnl": False,
                            "real_order": False,
                            "market_id": wide["market_id"],
                            "runner_id": wide["runner_id"],
                            "date": wide["date"],
                            "country_code": meta["country_code"],
                            "market_type": meta["market_type"],
                            "event_id": meta["event_id"],
                            "event_name": meta["event_name"],
                            "market_name": meta["market_name"],
                            "source_member": member.name,
                            "decision_timestamp_ms": wide["feature_timestamp_ms"],
                            "decision_state_timestamp_ms": wide["feature_state_timestamp_ms"],
                            "horizon_sec": horizon,
                            "horizon_source_timestamp_ms": future_ts,
                            "back_entry_atb": wide["best_back"],
                            "lay_exit_atl": wide.get(f"future_lay_{horizon}s"),
                            "lay_entry_atl": wide["best_lay"],
                            "back_exit_atb": wide.get(f"future_back_{horizon}s"),
                            "net_back_return": wide.get(f"net_back_return_{horizon}s"),
                            "net_lay_return": wide.get(f"net_lay_return_{horizon}s"),
                        })
            except Exception as exc:
                failures.append({"member": member.name, "error": repr(exc)})

    key_fields = ("market_id", "runner_id", "decision_timestamp_ms", "horizon_sec")
    keys = [tuple(row[field] for field in key_fields) for row in rows]
    duplicate_rows = len(keys) - len(set(keys))
    invalid_ts = sum(
        not isinstance(row["decision_timestamp_ms"], int)
        or not isinstance(row["decision_state_timestamp_ms"], int)
        or not isinstance(row["horizon_source_timestamp_ms"], int)
        for row in rows
    )
    rows_path = out_dir / "september_quote_markouts.csv"
    fields = sorted({key for row in rows for key in row})
    with rows_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "report_version": "september-2026-v1",
        "result_kind": "quote_markout",
        "simulated_fills": False,
        "strategy_pnl": False,
        "real_orders": False,
        "calibration_used": False,
        "september_is_sealed_evaluation": True,
        "commission_rate": 0.02,
        "latency_or_bet_delay_tuning": "none; PR #3 fixed 1000ms in-play latency and this run did not alter it",
        "source_revision": "origin/reconcile/jeff-book-semantics@f46147b6322f751a321b69c1c7749a105d0ac128",
        "archive": inventory["archive"],
        "eligible_markets": len(canonical),
        "selected_members": len(target_members),
        "rows": len(rows),
        "parser_failures": failures,
        "duplicate_output_identity_rows": duplicate_rows,
        "invalid_source_timestamp_rows": invalid_ts,
        "identity": {"fields": list(key_fields), "unique": duplicate_rows == 0},
        "exclusions": inventory["exclusions"],
        "official_semantics_source": "https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687396/Exchange+Stream+API",
        "payoff_sanity": {"atb": 2.0, "atl": 2.02, "back_then_lay": "2.00/2.02 - 1 < 0", "lay_then_back": "1 - 2.02/2.00 < 0"},
        "csv": str(rows_path),
    }
    (out_dir / "september_quote_markout_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, default=ARCHIVE)
    ap.add_argument("--out-dir", type=Path, default=Path("research/september_2026_eval_v1"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    inventory = scan_inventory(args.archive)
    (args.out_dir / "september_archive_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = evaluate(args.archive, inventory, args.out_dir)
    print(json.dumps({"inventory": str(args.out_dir / 'september_archive_inventory.json'), "report": str(args.out_dir / 'september_quote_markout_report.json'), "members": inventory['member_count'], "eligible_markets": inventory['eligible_market_count'], "rows": report['rows'], "failures": len(inventory['parser_failures']) + len(report['parser_failures'])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
