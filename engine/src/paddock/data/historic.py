"""Historic data fetch + unpack (Betfair historic data API).

`unpack()` is verified against real manually-downloaded tars across all
three plan tiers — Basic (GB horse racing, Sep 2026), Advanced (the same
Sep 2026 period at a richer tier), and Pro (GB+intl horse racing, Aug
2015-2017). All three use the same tar shape: per-market .bz2 files at
`<PLAN>/<year>/<Mon>/<day>/<eventId>/<marketId>.bz2`, plus one aggregate
per-event file (named after the eventId, no "1." prefix) that we skip —
see _is_market_file. Decompressed content is the same JSONL market-change
stream shape regardless of tier; only the per-runner field richness
differs (see paddock.data.manifest).

`fetch()` (the get_file_list/download_file path) is NOT verified against a
real account — the method names/signatures are confirmed against
betfairlightweight 2.24.0 source, but the exact from_day/from_month/
from_year string format Betfair's API expects for get_file_list is not
independently confirmed. Verify against a real response before relying on
it, and adjust `_month_str`/`_day_str` if the API rejects the format.

You must first "purchase" (free for Basic Plan, priced for Advanced/Pro)
the data you want at https://historicdata.betfair.com before
`get_my_data`/`get_file_list` will return anything for it — a manual step
in Betfair's UI this CLI can't do.
"""
from __future__ import annotations

import bz2
import hashlib
import json
import logging
import tarfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import betfairlightweight

from paddock.config.betfair_client import login, make_api_client
from paddock.config.settings import Settings
from paddock.data.manifest import DataPlan, append_manifest, detect_data_plan_bytes

logger = logging.getLogger(__name__)

DEFAULT_SPORT = "Horse Racing"
DEFAULT_PLAN = "Basic Plan"


def _day_str(d: date) -> str:
    return str(d.day)


def _month_str(d: date) -> str:
    return d.strftime("%b")  # e.g. "Jan" — verify against a real API response


def _year_str(d: date) -> str:
    return str(d.year)


def list_available_files(
    client: betfairlightweight.APIClient,
    from_date: date,
    to_date: date,
    sport: str = DEFAULT_SPORT,
    plan: str = DEFAULT_PLAN,
    market_types: list[str] | None = None,
    countries: list[str] | None = None,
) -> list[str]:
    """Returns the list of remote file paths available to download."""
    result = client.historic.get_file_list(
        sport=sport,
        plan=plan,
        from_day=_day_str(from_date),
        from_month=_month_str(from_date),
        from_year=_year_str(from_date),
        to_day=_day_str(to_date),
        to_month=_month_str(to_date),
        to_year=_year_str(to_date),
        market_types_collection=market_types,
        countries_collection=countries,
    )
    if isinstance(result, list):
        return result
    return result.get("fileList", []) if isinstance(result, dict) else []


def fetch(
    settings: Settings,
    from_date: date,
    to_date: date,
    store_dir: Path,
    sport: str = DEFAULT_SPORT,
    plan: str = DEFAULT_PLAN,
    market_types: list[str] | None = None,
    countries: list[str] | None = None,
) -> list[Path]:
    """Downloads every file in range into store_dir. Returns local paths."""
    market_types = market_types or ["WIN"]
    countries = countries or ["GB"]
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)

    client = make_api_client(settings)
    login(client, settings)
    try:
        remote_files = list_available_files(
            client, from_date, to_date, sport, plan, market_types, countries
        )
        logger.info("Found %d historic files to download", len(remote_files))
        downloaded: list[Path] = []
        for remote_path in remote_files:
            local_name = client.historic.download_file(
                file_path=remote_path, store_directory=str(store_dir)
            )
            downloaded.append(Path(local_name))
        return downloaded
    finally:
        client.logout()


def _market_id_from_name(name: str) -> str:
    # Historic filenames are typically the market id itself, sometimes with
    # a compression suffix (e.g. "1.170258213.bz2"). Strip known suffixes.
    stem = name
    for suffix in (".bz2", ".tar"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def _is_market_file(name: str) -> bool:
    # Real historic tars also contain one aggregate per-event file (named
    # after the eventId, no "1." prefix, e.g. "36004367.bz2") alongside the
    # per-market files ("1.<digits>.bz2") — confirmed against real Basic,
    # Advanced and Pro downloads. We only want the per-market files.
    market_id = _market_id_from_name(Path(name).name)
    return market_id.startswith("1.") and market_id[2:].isdigit()


@dataclass(frozen=True)
class UnpackedMarket:
    market_id: str
    path: Path
    data_plan: DataPlan
    market_time: str | None
    venue: str | None
    event_name: str | None
    country_code: str | None
    market_type: str | None
    size_bytes: int
    update_count: int


@dataclass(frozen=True)
class DuplicateSkipped:
    """A market_id already exists on disk under the same plan with
    byte-identical content — not rewritten, not an error."""

    market_id: str
    data_plan: str
    path: Path


@dataclass(frozen=True)
class HashConflict:
    """A market_id already exists on disk under the same plan but with
    DIFFERENT content — never overwritten. Needs a human to look at it."""

    market_id: str
    data_plan: str
    path: Path
    existing_sha256: str
    new_sha256: str


@dataclass(frozen=True)
class SkippedGroup:
    """A whole (plan, year, month) group where nothing matched the country
    filter — e.g. an entirely non-GB month when countries=["GB"]."""

    data_plan: str
    year: str
    month: str
    market_count: int
    total_bytes: int


@dataclass(frozen=True)
class UnpackResult:
    written: list[UnpackedMarket] = field(default_factory=list)
    duplicates_skipped: list[DuplicateSkipped] = field(default_factory=list)
    conflicts: list[HashConflict] = field(default_factory=list)
    skipped_groups: list[SkippedGroup] = field(default_factory=list)


@dataclass(frozen=True)
class _Metadata:
    year: str
    month: str
    market_time: str | None
    venue: str | None
    event_name: str | None
    country_code: str | None
    market_type: str | None


def _parse_metadata(raw: bytes, market_id: str) -> _Metadata:
    year, month = "unknown", "unknown"
    market_time = venue = event_name = country_code = market_type = None
    try:
        first_update = json.loads(raw.split(b"\n", 1)[0])
        for change in first_update.get("mc", []):
            definition = change.get("marketDefinition")
            if definition:
                market_time = definition.get("marketTime")
                venue = definition.get("venue")
                event_name = definition.get("eventName")
                country_code = definition.get("countryCode")
                market_type = definition.get("marketType")
                if market_time:
                    year = market_time[0:4]
                    month = market_time[5:7]
                break
    except (ValueError, KeyError, IndexError):
        logger.warning("Could not parse market time from %s, filing under unknown/", market_id)
    return _Metadata(year, month, market_time, venue, event_name, country_code, market_type)


def _passes_filter(
    metadata: _Metadata, countries: list[str] | None, market_types: list[str] | None
) -> bool:
    if countries and metadata.country_code not in countries:
        return False
    if market_types and metadata.market_type not in market_types:
        return False
    return True


def _iter_raw_markets(archive_path: Path):
    """Yields (market_id, raw_bytes) for every per-market file in the
    archive, decompressed. Sole responsibility: read the archive."""
    if archive_path.suffix == ".tar":
        with tarfile.open(archive_path, "r") as tar:
            for member in tar.getmembers():
                if not member.isfile() or not _is_market_file(member.name):
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                raw = bz2.decompress(extracted.read())
                yield _market_id_from_name(Path(member.name).name), raw
    else:
        with bz2.BZ2File(archive_path, "rb") as f:
            raw = f.read()
        yield _market_id_from_name(archive_path.name), raw


def unpack(
    archive_path: Path,
    dest_root: Path,
    countries: list[str] | None = None,
    market_types: list[str] | None = None,
) -> UnpackResult:
    """Unpacks a downloaded historic file into
    dest_root/<plan>/<year>/<month>/<market_id> plain JSON-lines files.

    `plan` (basic/advanced/pro) comes from a byte-scan of the market's own
    content (paddock.data.manifest.detect_data_plan_bytes) — never from the
    tar's own folder labels or the filename, since those are a hint at
    best (see the module docstring).

    `countries`/`market_types` filter by each market's own countryCode/
    marketType (e.g. countries=["GB"], market_types=["WIN"]) — markets
    that don't match are never written to disk. A whole (plan, year,
    month) group where nothing at all matched the country filter is
    reported in `.skipped_groups` rather than silently vanishing.

    Never overwrites an existing file: if the same market_id shows up
    again under the same plan, the new content is hashed against what's
    already on disk — byte-identical is silently skipped
    (`.duplicates_skipped`), different content is reported
    (`.conflicts`) and left untouched either way.

    Year/month for the destination path are read from each market's own
    first marketDefinition line rather than the source filename/tar path —
    that's the one source of truth actually present in the data itself.
    """
    dest_root = Path(dest_root)
    result = UnpackResult()

    # (plan, year, month) -> {"count", "bytes", "country_match_count"} —
    # tracked for every market considered, filtered or not, so we can spot
    # a group where the country filter zeroed out everything.
    group_totals: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
        lambda: {"count": 0, "bytes": 0, "country_match_count": 0}
    )

    for market_id, raw in _iter_raw_markets(Path(archive_path)):
        metadata = _parse_metadata(raw, market_id)
        plan = detect_data_plan_bytes(raw)
        group_key = (plan, metadata.year, metadata.month)
        totals = group_totals[group_key]
        totals["count"] += 1
        totals["bytes"] += len(raw)
        if not countries or metadata.country_code in countries:
            totals["country_match_count"] += 1

        if not _passes_filter(metadata, countries, market_types):
            continue

        dest = dest_root / plan / metadata.year / metadata.month / market_id
        new_hash = hashlib.sha256(raw).hexdigest()
        if dest.exists():
            existing_hash = hashlib.sha256(dest.read_bytes()).hexdigest()
            if existing_hash == new_hash:
                result.duplicates_skipped.append(DuplicateSkipped(market_id, plan, dest))
            else:
                result.conflicts.append(
                    HashConflict(market_id, plan, dest, existing_hash, new_hash)
                )
            continue  # never overwrite, identical or not

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        result.written.append(
            UnpackedMarket(
                market_id=market_id,
                path=dest,
                data_plan=plan,
                market_time=metadata.market_time,
                venue=metadata.venue,
                event_name=metadata.event_name,
                country_code=metadata.country_code,
                market_type=metadata.market_type,
                size_bytes=len(raw),
                update_count=raw.count(b"\n") + 1,
            )
        )

    if countries:
        for (plan, year, month), totals in group_totals.items():
            if totals["count"] > 0 and totals["country_match_count"] == 0:
                result.skipped_groups.append(
                    SkippedGroup(plan, year, month, totals["count"], totals["bytes"])
                )

    append_manifest(
        dest_root,
        [
            {
                "market_id": m.market_id,
                "data_plan": m.data_plan,
                "venue": m.venue,
                "market_time": m.market_time,
                "country_code": m.country_code,
                "market_type": m.market_type,
                # Pro data runs far denser than Advanced/Basic (real: Aug
                # 2015 Pro averages ~50ms between updates vs multi-second
                # gaps for Basic/Advanced) — recorded so pacing/UI code can
                # decide whether to throttle without re-scanning the file.
                "update_count": m.update_count,
            }
            for m in result.written
        ],
    )
    return result


def summarize(result: UnpackResult) -> dict:
    """Per-(plan, month) breakdown, plus overall totals and the
    duplicate/conflict/skipped-group reports."""
    by_group: dict[tuple[str, str, str], list[UnpackedMarket]] = defaultdict(list)
    for m in result.written:
        by_group[(m.data_plan, m.market_time[0:4] if m.market_time else "unknown", m.market_time[5:7] if m.market_time else "unknown")].append(m)

    groups = {}
    for (plan, year, month), markets in sorted(by_group.items()):
        times = sorted(m.market_time for m in markets if m.market_time)
        venues = Counter(m.venue for m in markets if m.venue)
        groups[f"{plan}/{year}-{month}"] = {
            "market_count": len(markets),
            "date_range": (times[0], times[-1]) if times else (None, None),
            "venues": dict(venues.most_common()),
            "total_size_bytes": sum(m.size_bytes for m in markets),
        }

    times = sorted(m.market_time for m in result.written if m.market_time)
    return {
        "market_count": len(result.written),
        "date_range": (times[0], times[-1]) if times else (None, None),
        "total_size_bytes": sum(m.size_bytes for m in result.written),
        "data_plans": dict(Counter(m.data_plan for m in result.written)),
        "groups": groups,
        "duplicates_skipped": [
            {"market_id": d.market_id, "data_plan": d.data_plan, "path": str(d.path)}
            for d in result.duplicates_skipped
        ],
        "conflicts": [
            {
                "market_id": c.market_id,
                "data_plan": c.data_plan,
                "path": str(c.path),
                "existing_sha256": c.existing_sha256,
                "new_sha256": c.new_sha256,
            }
            for c in result.conflicts
        ],
        "skipped_groups": [
            {
                "data_plan": g.data_plan,
                "year": g.year,
                "month": g.month,
                "market_count": g.market_count,
                "total_bytes": g.total_bytes,
            }
            for g in result.skipped_groups
        ],
    }
