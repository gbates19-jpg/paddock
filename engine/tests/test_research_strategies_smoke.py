"""Smoke tests for the 3 candidate research strategies (see
docs/strategy-research.md) — run over the 2 bundled real Pro-plan fixtures
(fill_model=ladder, matching what the actual research batches use) purely
to catch a crash/obvious wiring bug cheaply before committing to a
989-market run. Not a verdict on edge — that's the full-batch backtest.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paddock.sim.harness import run_simulation
from paddock.sim.store import connect
from paddock.strategies.drift_following import DriftSteamFollower
from paddock.strategies.favourite_longshot_bias import FavouriteLongshotBias
from paddock.strategies.market_maker import LadderMarketMaker

RESOURCES = Path(__file__).parent / "resources"
PRO_FIXTURES = [RESOURCES / "1.120089104", RESOURCES / "1.170258213"]


@pytest.mark.parametrize(
    "strategy_cls",
    [DriftSteamFollower, FavouriteLongshotBias, LadderMarketMaker],
)
def test_strategy_runs_clean_over_bundled_pro_fixtures(strategy_cls, tmp_path):
    run_id = run_simulation(
        strategy_cls,
        PRO_FIXTURES,
        speed=0,
        commission_rate=0.02,
        fill_model="ladder",
        data_dir=tmp_path,
    )

    with connect(tmp_path) as con:
        con.row_factory = sqlite3.Row
        run = con.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        assert run is not None
        assert run["fill_model"] == "ladder"

        markets = con.execute(
            "SELECT * FROM run_markets WHERE run_id = ?", (run_id,)
        ).fetchall()
        assert len(markets) == len(PRO_FIXTURES)


def test_market_maker_nets_flat_or_reports_unhedged(tmp_path):
    """The one invariant that matters for a market maker specifically:
    every market ends with either a flat net position (BACK matched size
    == LAY matched size across all mm_back/mm_lay/mm_flatten orders) or an
    explicit position.unhedged — never a silent naked residual with
    nothing on the bus to explain it. No running loop here (plain
    synchronous test), so EventBus.publish() takes its pre-bind
    synchronous path — subscribing and draining with get_nowait() is safe."""
    from paddock.bus.bus import EventBus
    from paddock.bus.events import PositionUnhedged

    bus = EventBus()
    queue = bus.subscribe(maxsize=0)

    run_id = run_simulation(
        LadderMarketMaker,
        PRO_FIXTURES,
        speed=0,
        commission_rate=0.02,
        fill_model="ladder",
        data_dir=tmp_path,
        bus=bus,
    )

    unhedged_markets = set()
    while not queue.empty():
        event = queue.get_nowait()
        if isinstance(event, PositionUnhedged):
            unhedged_markets.add(event.market_id)

    with connect(tmp_path) as con:
        con.row_factory = sqlite3.Row
        orders = con.execute(
            "SELECT market_id, side, role, matched_size FROM run_orders WHERE run_id = ?",
            (run_id,),
        ).fetchall()

    net_by_market: dict[str, float] = {}
    for o in orders:
        if o["role"] not in ("mm_back", "mm_lay", "mm_flatten"):
            continue
        sign = 1 if o["side"] == "back" else -1
        net_by_market[o["market_id"]] = net_by_market.get(o["market_id"], 0.0) + sign * o["matched_size"]

    for market_id, net in net_by_market.items():
        if market_id in unhedged_markets:
            continue
        assert abs(round(net, 2)) <= 0.01, f"{market_id} left a silent naked residual of {net}"
