from __future__ import annotations

import bz2
from pathlib import Path

from paddock.data.historic import unpack
from paddock.data.manifest import data_plan_for, load_manifest, manifest_path

BASIC_MARKET = Path(__file__).parent / "resources" / "1.261851533"
RICH_MARKET = Path(__file__).parent / "resources" / "1.170258213"


def _as_bz2(src: Path, dest: Path) -> Path:
    dest.write_bytes(bz2.compress(src.read_bytes()))
    return dest


def test_unpack_writes_manifest_with_correct_data_plan(tmp_path):
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    result = unpack(archive, tmp_path / "out")

    assert len(result.written) == 1
    assert result.written[0].data_plan == "basic"
    assert manifest_path(tmp_path / "out").exists()
    manifest = load_manifest(tmp_path / "out")
    assert manifest["1.261851533"]["data_plan"] == "basic"
    assert manifest["1.261851533"]["venue"] == "Newcastle"


def test_unpack_lays_out_by_plan_then_year_then_month(tmp_path):
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    result = unpack(archive, tmp_path / "out")

    assert result.written[0].path == tmp_path / "out" / "basic" / "2026" / "09" / "1.261851533"
    assert result.written[0].path.exists()


def test_data_plan_for_uses_manifest_when_present(tmp_path):
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    unpack(archive, tmp_path / "out")
    unpacked_path = tmp_path / "out" / "basic" / "2026" / "09" / "1.261851533"

    assert data_plan_for(unpacked_path, tmp_path / "out") == "basic"


def test_data_plan_for_falls_back_to_detection_without_manifest(tmp_path):
    # a file that never went through unpack() (e.g. a bundled test fixture
    # copied in directly) has no manifest entry at all
    assert data_plan_for(BASIC_MARKET, data_root=tmp_path) == "basic"
    assert data_plan_for(BASIC_MARKET, data_root=None) == "basic"


def test_unpack_never_overwrites_identical_duplicate(tmp_path):
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    first = unpack(archive, tmp_path / "out")
    written_at = first.written[0].path.stat().st_mtime_ns

    second = unpack(archive, tmp_path / "out")

    assert second.written == []
    assert len(second.duplicates_skipped) == 1
    assert second.duplicates_skipped[0].market_id == "1.261851533"
    assert first.written[0].path.stat().st_mtime_ns == written_at  # untouched


def test_unpack_reports_conflict_without_overwriting(tmp_path):
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    unpack(archive, tmp_path / "out")

    # tamper with the on-disk copy, then "unpack" the same market_id again
    # with different content
    existing_path = tmp_path / "out" / "basic" / "2026" / "09" / "1.261851533"
    original_content = existing_path.read_bytes()
    existing_path.write_bytes(original_content + b"\n")

    result = unpack(archive, tmp_path / "out")

    assert result.written == []
    assert len(result.conflicts) == 1
    assert result.conflicts[0].market_id == "1.261851533"
    assert result.conflicts[0].existing_sha256 != result.conflicts[0].new_sha256
    # still untouched — the tampered content is what's on disk
    assert existing_path.read_bytes() == original_content + b"\n"


def test_unpack_reports_entirely_non_matching_country_group(tmp_path):
    # BASIC_MARKET is GB — filtering to a country it never matches should
    # report the whole (plan, year, month) group as skipped, not silently
    # write nothing.
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    result = unpack(archive, tmp_path / "out", countries=["IE"])

    assert result.written == []
    assert len(result.skipped_groups) == 1
    assert result.skipped_groups[0].data_plan == "basic"
    assert result.skipped_groups[0].market_count == 1
