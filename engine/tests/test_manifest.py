from __future__ import annotations

import bz2
from pathlib import Path

from paddock.data.historic import unpack
from paddock.data.manifest import data_plan_for, load_manifest, manifest_path

BASIC_MARKET = Path(__file__).parent / "resources" / "1.261851533"


def _as_bz2(src: Path, dest: Path) -> Path:
    dest.write_bytes(bz2.compress(src.read_bytes()))
    return dest


def test_unpack_writes_manifest_with_correct_data_plan(tmp_path):
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    unpack(archive, tmp_path / "out")

    assert manifest_path(tmp_path / "out").exists()
    manifest = load_manifest(tmp_path / "out")
    assert manifest["1.261851533"]["data_plan"] == "basic"
    assert manifest["1.261851533"]["venue"] == "Newcastle"


def test_data_plan_for_uses_manifest_when_present(tmp_path):
    archive = _as_bz2(BASIC_MARKET, tmp_path / "1.261851533.bz2")
    unpack(archive, tmp_path / "out")
    unpacked_path = tmp_path / "out" / "2026" / "09" / "1.261851533"

    assert data_plan_for(unpacked_path, tmp_path / "out") == "basic"


def test_data_plan_for_falls_back_to_detection_without_manifest(tmp_path):
    # a file that never went through unpack() (e.g. a bundled test fixture
    # copied in directly) has no manifest entry at all
    assert data_plan_for(BASIC_MARKET, data_root=tmp_path) == "basic"
    assert data_plan_for(BASIC_MARKET, data_root=None) == "basic"
