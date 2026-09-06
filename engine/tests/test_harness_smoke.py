"""Part A #7 smoke test: the baseline over one bundled sample market file in <5s.

Uses tests/resources/1.261851533 — a real Basic Plan (free) historic file:
Newcastle, WIN, GB, settled 2026-09-03, ~99KB. PassiveObserver places no
orders, so this only proves the data/sim/bus/runs.db pipeline runs cleanly
end to end — it says nothing about order matching (see test_commission.py's
docstring for why that needs the other, richer bundled fixture instead).

fill_model=ltp_cross because this is Basic Plan data — fill_model=ladder
would (correctly) refuse to run against it, see test_fill_models.py.
"""
from __future__ import annotations

import time
from pathlib import Path

from paddock.sim.harness import run_simulation
from paddock.sim.store import connect
from paddock.strategies.passive import PassiveObserver

SAMPLE_MARKET = Path(__file__).parent / "resources" / "1.261851533"


def test_smoke_passive_strategy_over_bundled_market_under_5s(tmp_path):
    start = time.monotonic()
    run_id = run_simulation(
        PassiveObserver,
        [SAMPLE_MARKET],
        speed=0,
        commission_rate=0.02,
        fill_model="ltp_cross",
        data_dir=tmp_path,
    )
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, f"smoke test took {elapsed:.2f}s, expected < 5s"

    with connect(tmp_path) as con:
        run = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        assert run is not None
        assert run["strategy"] == "PassiveObserver"
        assert run["commission_rate"] == 0.02
        assert run["fill_model"] == "ltp_cross"
