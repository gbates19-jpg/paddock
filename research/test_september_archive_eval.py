"""Synthetic archive regressions for the sealed September evaluator."""
from datetime import datetime, timezone
import bz2
import io
import json
import tarfile

from research.september_archive_eval import evaluate, scan_inventory


def _market_lines():
    off = 1_500_000_000_000
    base = off - 300_000
    definition = {
        "marketTime": datetime.fromtimestamp(off / 1000, timezone.utc).isoformat(),
        "status": "OPEN", "inPlay": False, "countryCode": "GB", "marketType": "WIN",
        "eventId": "event-1", "eventName": "Synthetic GB", "name": "1m WIN",
        "runners": [{"id": 1, "status": "ACTIVE", "name": "Runner"}],
    }
    events = [{"pt": base - 1, "mc": [{"id": "1.1", "marketDefinition": definition}]}]
    for ts in range(base, base + 65_000, 5_000):
        events.append({"pt": ts, "mc": [{"id": "1.1", "rc": [{"id": 1, "batb": [[0, 2.0, 10]], "batl": [[0, 2.02, 10]]}]}]})
    return b"\n".join(json.dumps(e).encode() for e in events) + b"\n"


def _archive(tmp_path):
    archive = tmp_path / "data.tar"
    payload = bz2.compress(_market_lines())
    info = tarfile.TarInfo("ADVANCED/2026/Sep/1/event-1/1.1.bz2")
    info.size = len(payload)
    with tarfile.open(archive, "w") as tf:
        tf.addfile(info, io.BytesIO(payload))
    return archive


def test_compressed_indexed_september_archive(tmp_path):
    archive = _archive(tmp_path)
    inventory = scan_inventory(archive)
    assert inventory["member_count"] == 1
    assert inventory["compressed_members"] == 1
    assert inventory["eligible_market_count"] == 1
    assert inventory["parser_failures"] == []
    report = evaluate(archive, inventory, tmp_path / "out")
    assert report["eligible_markets"] == 1
    assert report["parser_failures"] == []
    assert report["duplicate_output_identity_rows"] == 0
    assert report["invalid_source_timestamp_rows"] == 0
    assert report["result_kind"] == "quote_markout"
