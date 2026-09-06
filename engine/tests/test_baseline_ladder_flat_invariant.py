"""Flat-at-off invariant check against a real Pro-tier market (as opposed
to test_baseline_flat_invariant.py's synthetic ones, which give exact
control over the ltp sequence but can't stand in for real order-book
liquidity).

tests/resources/1.120089104 is a real Aug 2015 Pro fixture (GB, £0 —
Betfair ages historic plans out to free after enough time) picked because
it's one of the real markets used to validate the liquidity-taking closer
fix: under fill_model=ladder, entry matches, the passive exit never
crosses, and the closer (aggressive LAY at the current best
available_to_lay, per the "take liquidity, don't rest" fix) matches on its
first attempt. Locks in that real-data outcome as a regression test.
"""
from __future__ import annotations

from pathlib import Path

from paddock.sim.harness import run_simulation
from paddock.sim.store import connect
from paddock.strategies.baseline import BaselineFavouriteScalp

PRO_MARKET = Path(__file__).parent / "resources" / "1.120089104"


def test_ladder_closer_takes_liquidity_and_closes_flat_on_real_pro_data(tmp_path):
    run_id = run_simulation(
        BaselineFavouriteScalp,
        [PRO_MARKET],
        speed=0,
        commission_rate=0.02,
        fill_model="ladder",
        data_dir=tmp_path,
        strategy_kwargs={"stake": 2.0},
    )

    with connect(tmp_path) as con:
        orders = con.execute(
            "SELECT * FROM run_orders WHERE run_id = ? ORDER BY side, price", (run_id,)
        ).fetchall()

        back_matched = sum(o["matched_size"] for o in orders if o["side"] == "back")
        lay_matched = sum(o["matched_size"] for o in orders if o["side"] == "lay")
        assert back_matched == lay_matched  # flat: net position zero
        assert back_matched > 0  # and it's not flat because nothing happened

        # the passive exit never crosses on this fixture, but the closer
        # (taking liquidity, not resting) does — both lay orders present
        lay_orders = [o for o in orders if o["side"] == "lay"]
        assert len(lay_orders) == 2
        assert any(o["matched_size"] == 0 for o in lay_orders)  # exit: never crossed
        assert any(o["matched_size"] > 0 for o in lay_orders)  # closer: took liquidity

        market = con.execute(
            "SELECT * FROM run_markets WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert market["bet_count"] == 2  # entry + whichever lay leg matched
