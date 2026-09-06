"""Step 3: BaselineFavouriteScalp proven end to end against the bundled
Basic Plan fixture under fill_model=ltp_cross, per the fill-model decision
(ladder would correctly refuse — see test_fill_models.py).

Real observed outcome for this fixture: the back leg never crosses (ltp
never rises back to 1.43 after placement) and gets cancelled at the 30s
window; the lay leg does cross and fully matches. That's a legitimate,
realistic scalp outcome, not a broken test — the strategy's job here is to
prove the wiring (bus events, runs.db, order lifecycle), not to win.

Along the way this caught a real bug worth guarding against regressing:
flumine's BaseStrategy defaults to max_live_trade_count=1, which silently
voided the second (lay) leg as a STRATEGY_EXPOSURE violation until
BaselineFavouriteScalp.__init__ set it to 2.
"""
from __future__ import annotations

from pathlib import Path

from paddock.sim.harness import run_simulation
from paddock.sim.store import connect
from paddock.strategies.baseline import BaselineFavouriteScalp

BASIC_MARKET = Path(__file__).parent / "resources" / "1.261851533"


def test_baseline_places_both_legs_and_records_them(tmp_path):
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
            "SELECT * FROM run_orders WHERE run_id = ? ORDER BY side", (run_id,)
        ).fetchall()
        assert len(orders) == 2
        sides = {o["side"] for o in orders}
        assert sides == {"back", "lay"}

        back = next(o for o in orders if o["side"] == "back")
        lay = next(o for o in orders if o["side"] == "lay")
        assert lay["price"] < back["price"], "lay must be placed lower than back"
        assert back["status"] == "Execution complete"
        assert lay["status"] == "Execution complete"

        market = con.execute(
            "SELECT * FROM run_markets WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert market is not None
        assert market["bet_count"] == 1  # only the matched leg counts as a settled bet
