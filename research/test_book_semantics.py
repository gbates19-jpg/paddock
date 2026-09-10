"""Regression tests for Betfair atb/atl action semantics.

Official reference:
https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687396/Exchange+Stream+API

The Stream API defines atb/atl as Available To Back / Available To Lay.
These tests intentionally treat those names as the action available to the
incoming bettor, rather than relabelling them as conventional bid/ask sides.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

from research.event_study import _net_back_return, _net_lay_return, parse_market
from research.inplay.inplay_event_study import ret_back, ret_lay
import pytest


ATB = 2.00
ATL = 2.02


def test_unchanged_book_loses_spread_in_both_directions():
    assert _net_back_return(ATB, ATL, 0.0) == pytest.approx(-(0.02 / 2.02))
    assert _net_lay_return(ATL, ATB, 0.0) == pytest.approx(-0.02 / 2.00)
    assert ret_back(ATB, ATL, 0.0) == pytest.approx(-(0.02 / 2.02))
    assert ret_lay(ATL, ATB, 0.0) == pytest.approx(-0.02 / 2.00)


def test_independent_ten_pound_matching_example():
    # BACK £10 at 2.00, then LAY at 2.02 with equalised payout.
    lay_stake = 10.0 * ATB / ATL
    back_win = 10.0 * (ATB - 1.0) - lay_stake * (ATL - 1.0)
    back_lose = -10.0 + lay_stake
    assert abs(back_win - back_lose) < 1e-12
    assert back_win < 0

    # LAY £10 at 2.02, then BACK at 2.00 with equalised liability.
    back_stake = 10.0 * ATL / ATB
    lay_win = -10.0 * (ATL - 1.0) + back_stake * (ATB - 1.0)
    lay_lose = 10.0 - back_stake
    assert abs(lay_win - lay_lose) < 1e-12
    assert lay_win < 0


def test_preoff_rows_use_atb_for_back_entry_and_atl_for_lay_exit(tmp_path: Path):
    off = 1_500_000_000_000
    base = off - 300_000
    market_time = datetime.fromtimestamp(off / 1000, timezone.utc).isoformat()
    definition = {
        "marketTime": market_time,
        "status": "OPEN",
        "inPlay": False,
        "runners": [{"id": 1, "status": "ACTIVE"}],
    }
    events = [
        {"pt": base - 1, "mc": [{"id": "1.1", "marketDefinition": definition}]},
        {"pt": base, "mc": [{"id": "1.1", "rc": [{"id": 1, "atb": [[ATB, 100]], "atl": [[ATL, 100]]}]}]},
        {"pt": base + 5_000, "mc": [{"id": "1.1", "rc": [{"id": 1, "atb": [[ATB, 100]], "atl": [[ATL, 100]]}]}]},
        {"pt": base + 15_000, "mc": [{"id": "1.1", "rc": [{"id": 1, "atb": [[ATB, 100]], "atl": [[ATL, 100]]}]}]},
    ]
    path = tmp_path / "1.1"
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    rows = parse_market(path, commission=0.0)
    row = next(row for row in rows if row["snapshot_sec_to_off"] == 300)
    assert row["net_back_return_5s"] < 0
    assert row["net_lay_return_5s"] < 0
    assert row["net_back_return_5s"] == pytest.approx(-(0.02 / 2.02))
    assert row["net_lay_return_5s"] == pytest.approx(-0.02 / 2.00)
