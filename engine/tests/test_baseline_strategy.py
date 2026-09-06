"""Step 3: BaselineFavouriteScalp proven end to end against the bundled
Basic Plan fixture under fill_model=ltp_cross, per the fill-model decision
(ladder would correctly refuse — see test_fill_models.py).

Real observed outcome for this fixture: the favourite's ltp never rises
back to the entry price (1.43) after placement, so entry never matches and
— per the sequential-legs design (test_baseline_flat_invariant.py) — no
exit is ever placed, since exit placement is gated on entry having some
matched size. One cancelled, unmatched order; flat; zero risk taken. Not a
broken test — proving the wiring (bus events, runs.db, order lifecycle),
not a winning bet, is the point of this fixture.

Along the way this caught a real bug worth guarding against regressing:
flumine's BaseStrategy defaults to max_live_trade_count=1, which silently
voided the second leg as a STRATEGY_EXPOSURE violation until
BaselineFavouriteScalp.__init__ set it to 2.
"""
from __future__ import annotations

from pathlib import Path

from paddock.sim.harness import run_simulation
from paddock.sim.store import connect
from paddock.strategies.baseline import BaselineFavouriteScalp

BASIC_MARKET = Path(__file__).parent / "resources" / "1.261851533"


def test_baseline_entry_never_crosses_stays_flat_against_real_data(tmp_path):
    run_id = run_simulation(
        BaselineFavouriteScalp,
        [BASIC_MARKET],
        speed=0,
        commission_rate=0.02,
        fill_model="ltp_cross",
        data_dir=tmp_path,
        strategy_kwargs={"stake": 2.0},
    )

    with connect(tmp_path) as con:
        run = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        assert run["strategy"] == "BaselineFavouriteScalp"
        assert run["fill_model"] == "ltp_cross"

        orders = con.execute(
            "SELECT * FROM run_orders WHERE run_id = ?", (run_id,)
        ).fetchall()
        assert len(orders) == 1
        assert orders[0]["side"] == "back"
        assert orders[0]["matched_size"] == 0.0
        assert orders[0]["status"] == "Execution complete"  # cancelled -> complete, unmatched

        market = con.execute(
            "SELECT * FROM run_markets WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert market is not None
        assert market["bet_count"] == 0  # nothing ever matched, nothing settled
