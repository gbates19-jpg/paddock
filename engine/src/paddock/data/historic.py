"""Historic data fetch + unpack (Betfair historic data API, Basic Plan/free).

`unpack()` is verified against a real manually-downloaded Basic Plan tar
(GB horse racing, Sep 2026): tar members are per-market .bz2 files at
`BASIC/<year>/<Mon>/<day>/<eventId>/<marketId>.bz2`, plus one aggregate
per-event file (named after the eventId, no "1." prefix) that we skip — see
_is_market_file. Decompressed content is the same JSONL market-change
stream shape as flumine's own bundled test fixture.

`fetch()` (the get_file_list/download_file path) is NOT verified against a
real account — the method names/signatures are confirmed against
betfairlightweight 2.24.0 source, but the exact from_day/from_month/
from_year string format Betfair's API expects for get_file_list is not
independently confirmed. Verify against a real response before relying on
it, and adjust `_month_str`/`_day_str` if the API rejects the format.

You must first "purchase" (free, $0 for Basic Plan) the data you want at
https://historicdata.betfair.com before `get_my_data`/`get_file_list` will
return anything for it — a manual step in Betfair's UI this CLI can't do.
"""
from __future__ import annotations

import bz2
import json
import logging
import tarfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import betfairlightweight

from paddock.config.betfair_client import login, make_api_client
from paddock.config.settings import Settings
from paddock.data.manifest import DataPlan, append_manifest, detect_data_plan

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
    # per-market files ("1.<digits>.bz2") — confirmed against a real Basic
    # Plan download. We only want the per-market files.
    market_id = _market_id_from_name(Path(name).name)
    return market_id.startswith("1.") and market_id[2:].isdigit()


@dataclass(frozen=True)
class UnpackedMarket:
    market_id: str
    path: Path
    market_time: str | None
    venue: str | None
    event_name: str | None
    size_bytes: int
    data_plan: DataPlan


def unpack(archive_path: Path, dest_root: Path) -> list[UnpackedMarket]:
    """Unpacks a downloaded historic file into dest_root/<year>/<month>/<market_id>
    plain JSON-lines files.

    Real Basic Plan downloads are a .tar whose members are per-market
    .bz2 files (confirmed against an actual download — path shape
    `BASIC/<year>/<Mon>/<day>/<eventId>/<marketId>.bz2`), plus one
    aggregate per-event file we skip (see _is_market_file). A lone .bz2 is
    also supported directly, for a single manually-downloaded market.

    Year/month for the destination path are read from each market's own
    first marketDefinition line rather than the source filename/tar path —
    that's the one source of truth actually present in the data itself.
    """
    archive_path = Path(archive_path)
    dest_root = Path(dest_root)
    written: list[UnpackedMarket] = []

    if archive_path.suffix == ".tar":
        with tarfile.open(archive_path, "r") as tar:
            for member in tar.getmembers():
                if not member.isfile() or not _is_market_file(member.name):
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                raw = bz2.decompress(extracted.read())
                market_id = _market_id_from_name(Path(member.name).name)
                written.append(_write_market_stream(raw, market_id, dest_root))
    else:
        with bz2.BZ2File(archive_path, "rb") as f:
            raw = f.read()
        written.append(
            _write_market_stream(raw, _market_id_from_name(archive_path.name), dest_root)
        )

    append_manifest(
        dest_root,
        [
            {
                "market_id": m.market_id,
                "data_plan": m.data_plan,
                "venue": m.venue,
                "market_time": m.market_time,
            }
            for m in written
        ],
    )
    return written


def _write_market_stream(raw: bytes, market_id: str, dest_root: Path) -> UnpackedMarket:
    first_line = raw.split(b"\n", 1)[0]
    year, month = "unknown", "unknown"
    market_time = venue = event_name = None
    try:
        first_update = json.loads(first_line)
        for change in first_update.get("mc", []):
            definition = change.get("marketDefinition")
            if definition:
                market_time = definition.get("marketTime")
                venue = definition.get("venue")
                event_name = definition.get("eventName")
                if market_time:
                    year = market_time[0:4]
                    month = market_time[5:7]
                break
    except (ValueError, KeyError, IndexError):
        logger.warning("Could not parse market time from %s, filing under unknown/", market_id)

    dest = dest_root / year / month / market_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return UnpackedMarket(
        market_id=market_id,
        path=dest,
        market_time=market_time,
        venue=venue,
        event_name=event_name,
        size_bytes=len(raw),
        data_plan=detect_data_plan(dest),
    )


def summarize(markets: list[UnpackedMarket]) -> dict:
    times = sorted(m.market_time for m in markets if m.market_time)
    venues = Counter(m.venue for m in markets if m.venue)
    data_plans = Counter(m.data_plan for m in markets)
    return {
        "market_count": len(markets),
        "date_range": (times[0], times[-1]) if times else (None, None),
        "venues": dict(venues.most_common()),
        "total_size_bytes": sum(m.size_bytes for m in markets),
        "data_plans": dict(data_plans),
    }
